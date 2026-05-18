package com.landup.placement;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.landup.common.ApiException;
import com.landup.floor.FloorAnchor;
import com.landup.floor.FloorAnchorRepository;
import com.landup.job.TokenUsage;
import com.landup.job.TokenUsageService;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * PlacementResult 오케스트레이션 — 기존 PlacementDbService.savePlacementObjects 흡수.
 *
 * 분해 구조 (PlacementDbService → 5개 전담 Service):
 *   ResultService      — PlacementResult INSERT + 하위 Service 에 위임
 *   ObjectService      — placement_objects (anchor_key → floor_anchor_id lookup 포함)
 *   VerificationService — placement_verifications
 *   CapLogService       — placement_cap_logs
 *   FailedObjectService — placement_failed_objects
 *
 * 신 스키마 특징:
 *   - 재배치(rerun) 시 기존 placement_result 덮어쓰지 않음 — 히스토리 누적.
 *     조회는 floor_detection_id 기준 최신(createdAt DESC) 1건만 노출.
 *   - placement_object 상위 FK: floor_detection_id → placement_result_id
 *   - furniture_standard_id 제거, object_type + floor_anchor_id 로 대체
 *   - label/pos_x_mm/pos_y_mm → object_type/center_x_mm/center_y_mm
 */
@Service
@RequiredArgsConstructor
public class PlacementResultService {

    private static final Logger log = LoggerFactory.getLogger(PlacementResultService.class);

    private final PlacementResultRepository resultRepo;
    private final PlacementObjectService objectService;
    private final PlacementVerificationService verificationService;
    private final PlacementCapLogService capLogService;
    private final PlacementFailedObjectService failedObjectService;
    private final TokenUsageService tokenUsageService;
    private final ObjectMapper objectMapper;
    private final FloorAnchorRepository anchorRepo;  // 2026-05-08 — anchor concept_area_id update

    // 2026-05-04 신설 — sub_path / main_artery 좌표 list ↔ JSON 문자열 변환용.
    // Python 응답의 [[x_mm, y_mm], ...] list 를 JSON 문자열로 직렬화해서 DB 저장.
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    // ══════════════ place worker 결과 반영 ══════════════

    /**
     * result 예상 필드:
     *   density_ratio, user_requirements, placed_count, failed_count,
     *   fallback_round, verification_passed, ref_quality_score, report_text, glb_path,
     *   objects[], verifications[], cap_logs[], failed_objects[]
     */
    @Transactional
    public Long applyPlaceResult(Long floorDetectionId, Map<String, Object> result) {
        PlacementResult pr = resultRepo.save(PlacementResult.builder()
                .floorDetectionId(floorDetectionId)
                .status(PlacementResult.ResultStatus.done)
                .densityRatio(asFloat(result.get("density_ratio")))
                .userRequirements(asString(result.get("user_requirements")))
                .placedCount(asInt(result.get("placed_count"), 0))
                .failedCount(asInt(result.get("failed_count"), 0))
                .fallbackRound(asInt(result.get("fallback_round"), 0))
                .verificationPassed((Boolean) result.get("verification_passed"))
                .refQualityScore(asFloat(result.get("ref_quality_score")))
                .reportText(asString(result.get("report_text")))
                .reportJson(toJsonString(result.get("report_json")))
                .glbPath(asString(result.get("glb_path")))
                // 2026-05-04 신설 — Python 응답의 sub_path / main_artery 좌표 list 를 JSON 문자열로 직렬화해서 DB 저장.
                // 빈 list / null 도 그대로 저장 (응답 시 deserialize 가 fallback 처리).
                .subPathJson(serializeJsonList(result.get("sub_path")))
                .mainArteryJson(serializeJsonList(result.get("main_artery")))
                .build());
        Long prId = pr.getId();

        // 하위 5종 저장을 각 전담 Service 에 위임
        objectService.insertBatch(prId, floorDetectionId, asList(result.get("objects")));
        verificationService.insertBatch(prId, asList(result.get("verifications")));
        capLogService.insertBatch(prId, asList(result.get("cap_logs")));
        failedObjectService.insertBatch(prId, asList(result.get("failed_objects")));

        // token_usage — 노드별 LLM 비용 집계 (upsert: (prId, nodeName) unique)
        for (Map<String, Object> tu : asList(result.get("token_usage"))) {
            tokenUsageService.upsert(TokenUsage.builder()
                    .placementResultId(prId)
                    .nodeName(asString(tu.get("node_name")))
                    .inputTokens(asInt(tu.get("input_tokens"), 0))
                    .outputTokens(asInt(tu.get("output_tokens"), 0))
                    .cacheReadTokens(asInt(tu.get("cache_read_tokens"), 0))
                    .cacheWriteTokens(asInt(tu.get("cache_write_tokens"), 0))
                    .model(asString(tu.get("model")))
                    .build());
        }

        // 2026-05-08 — anchor concept_area_id update (Python concept_area 노드 매핑 결과 반영).
        // space_data 시점엔 concept_area_id NULL 로 INSERT, place 시점에 매핑 후 응답에 박힘 (anchor_concept_mapping).
        // 매핑 누락 시 silent skip (로그만).
        List<Map<String, Object>> mapping = asList(result.get("anchor_concept_mapping"));
        int updated = 0;
        for (Map<String, Object> m : mapping) {
            String anchorKey = asString(m.get("anchor_key"));
            Long conceptAreaId = asLong(m.get("concept_area_id"));
            if (anchorKey == null || anchorKey.isEmpty() || conceptAreaId == null) continue;
            Optional<FloorAnchor> anchor = anchorRepo.findByFloorDetectionIdAndAnchorKey(floorDetectionId, anchorKey);
            if (anchor.isPresent()) {
                anchor.get().setConceptAreaId(conceptAreaId);
                anchorRepo.save(anchor.get());
                updated++;
            }
        }
        log.info("[applyPlaceResult] anchor concept_area_id update {}/{}건", updated, mapping.size());

        return prId;
    }

    // ══════════════ 조회 ══════════════

    public PlacementResult getOrThrow(Long id) {
        return resultRepo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "placement_result not found: " + id));
    }

    public Map<String, Object> getFullDetail(Long id) {
        PlacementResult pr = getOrThrow(id);
        Map<String, Object> out = new HashMap<>();
        out.put("id", pr.getId());
        out.put("floor_detection_id", pr.getFloorDetectionId());
        out.put("status", pr.getStatus().name());
        out.put("density_ratio", pr.getDensityRatio());
        out.put("placed_count", pr.getPlacedCount());
        out.put("failed_count", pr.getFailedCount());
        out.put("fallback_round", pr.getFallbackRound());
        out.put("verification_passed", pr.getVerificationPassed());
        out.put("ref_quality_score", pr.getRefQualityScore());
        out.put("report_text", pr.getReportText());
        out.put("glb_path", pr.getGlbPath());
        // 2026-05-04 신설 — DB 의 JSON 문자열을 list 로 deserialize 해서 응답 (프론트가 그대로 사용 가능).
        // sub_path: 여러 라인 형식 (각 가지 = 별 라인). List<List<List<Number>>>.
        // main_artery: 단일 라인 형식. List<List<Number>>.
        out.put("sub_path", deserializeJsonAny(pr.getSubPathJson()));
        out.put("main_artery", deserializeJsonAny(pr.getMainArteryJson()));
        out.put("created_at", pr.getCreatedAt());
        out.put("objects", objectService.listByResult(id));
        out.put("verifications", verificationService.listByResult(id));
        out.put("cap_logs", capLogService.listByResult(id));
        out.put("failed_objects", failedObjectService.listByResult(id));
        return out;
    }

    /**
     * 2026-05-04 신설 — Python 응답의 좌표 list (예: [[x_mm, y_mm], ...]) 를 JSON 문자열로 직렬화.
     * null / 빈 list 면 null 반환 (DB 컬럼 NULL).
     * 직렬화 실패 시 null + warning log.
     */
    private static String serializeJsonList(Object listObj) {
        if (listObj == null) return null;
        try {
            if (listObj instanceof List<?> l && l.isEmpty()) return null;
            return OBJECT_MAPPER.writeValueAsString(listObj);
        } catch (Exception e) {
            log.warn("[PlacementResultService] JSON 직렬화 실패: {}", e.getMessage());
            return null;
        }
    }

    /**
     * 2026-05-04 신설 - DB 의 JSON 문자열을 임의 형식으로 deserialize.
     * 사용처:
     * - main_artery: 단일 라인 List<List<Number>> 형식
     * - sub_path: 여러 라인 List<List<List<Number>>> 형식
     * Object 로 받아서 Jackson 이 자동으로 nested list 처리. Spring 응답 시점에 다시 JSON 직렬화.
     * null / 빈 문자열이면 null 반환. 역직렬화 실패 시 null + warning log.
     */
    private static Object deserializeJsonAny(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return OBJECT_MAPPER.readValue(json, Object.class);
        } catch (Exception e) {
            log.warn("[PlacementResultService] JSON 역직렬화 실패: {}", e.getMessage());
            return null;
        }
    }

    public List<PlacementResult> listByFloor(Long floorDetectionId) {
        return resultRepo.findAllByFloorDetectionIdOrderByCreatedAtDesc(floorDetectionId);
    }

    // ══════════════ 타입 유틸 ══════════════

    private static Float asFloat(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.floatValue();
        try { return Float.parseFloat(o.toString()); } catch (Exception e) { return null; }
    }

    private static Integer asInt(Object o, Integer fb) {
        if (o == null) return fb;
        if (o instanceof Number n) return n.intValue();
        try { return Integer.parseInt(o.toString()); } catch (Exception e) { return fb; }
    }

    private static Long asLong(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.longValue();
        try { return Long.parseLong(o.toString()); } catch (Exception e) { return null; }
    }

    private static String asString(Object o) {
        return o == null ? null : o.toString();
    }

    private String toJsonString(Object o) {
        if (o == null) return null;
        if (o instanceof String s) return s;
        try { return objectMapper.writeValueAsString(o); } catch (Exception e) { return null; }
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> asList(Object o) {
        return o instanceof List<?> l ? (List<Map<String, Object>>) l : new ArrayList<>();
    }
}
