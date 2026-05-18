package com.landup.project;

import com.landup.common.ApiException;
import com.landup.file.BrandManualRepository;
import com.landup.file.FloorArchiveRepository;
import com.landup.file.FloorArchive;
import com.landup.floor.FloorAnchor;
import com.landup.floor.FloorAnchorRepository;
import com.landup.floor.FloorDetectionRepository;
import com.landup.floor.FloorDetection;
import com.landup.floor.FloorDetectionService;
import com.landup.plan.PlanLimitService;
import com.landup.placement.PlacementObject;
import com.landup.placement.PlacementObjectRepository;
import com.landup.placement.PlacementResult;
import com.landup.placement.PlacementResultRepository;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * UserProject CRUD + stage 분기 — 기존 UserProjectService 대체.
 *
 * 필드명 변경:
 *   - pdfFileId       → pdfId
 *   - brandAnalysisId → brandManualId
 *   - placementResultId 신규 FK
 *
 * layout_objects 변환 (신 스키마):
 *   - label       → object_type
 *   - posXMm      → x_mm      (프론트 호환 키 유지: PlacementObject.centerXMm 사용)
 *   - posYMm      → y_mm
 *   - rotationDeg → angle_deg
 *   - extraJson(placed_because 등) → placed_because 컬럼 직접 참조
 *
 * placement_objects 조회: floor_detection_id 직결 → placement_result 중간 단계 경유
 *   resolveLatestPlacementResultId() 로 최신 결과 id 추출 후 findAllByPlacementResultId.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class UserProjectService {

    private static final DateTimeFormatter NAME_FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    private final UserProjectRepository repo;
    private final FloorArchiveRepository floorArchiveRepo;
    private final BrandManualRepository brandRepo;
    private final FloorDetectionRepository floorRepo;
    private final FloorDetectionService floorDetectionService;
    private final PlacementResultRepository placementResultRepo;
    private final PlacementObjectRepository placementObjectRepo;
    private final FloorAnchorRepository floorAnchorRepo;
    private final com.landup.concept.ConceptAreaRepository conceptAreaRepo;  // 2026-05-01 Phase 4-2
    private final PlanLimitService planLimitService;

    // ══════════════ 생성/첨부 ══════════════

    @Transactional
    public UserProject createStub(User user, Long floorArchiveId) {
        planLimitService.checkConcurrentLimit(user);
        UserProject project = repo.save(UserProject.builder()
                .userId(user.getId())
                .floorArchiveId(floorArchiveId)
                .status(UserProject.ProjectState.processing)
                .name(LocalDateTime.now().format(NAME_FMT))
                .build());
        planLimitService.checkProjectLimit(user, project.getId());
        return project;
    }

    @Transactional
    public UserProject createFromWorker(Long userId, Long floorArchiveId, Long brandManualId, Long floorDetectionId) {
        return repo.save(UserProject.builder()
                .userId(userId)
                .floorArchiveId(floorArchiveId)
                .brandManualId(brandManualId)
                .floorDetectionId(floorDetectionId)
                .status(UserProject.ProjectState.done)
                .name(LocalDateTime.now().format(NAME_FMT))
                .build());
    }

    // 2026-05-04 (H1 fix) - WHERE col IS NULL conditional update 로 변경.
    //   JPA save() dirty checking 이 전체 row UPDATE 라 동시 attach 시 stale 값으로 덮어쓰기 발생.
    //   conditional update = 이미 박혀있으면 silently no-op (log warning). race 자체 발생 X.
    //   재업로드 시나리오는 별도 메서드 (필요 시 신설) 로 처리.

    @Transactional
    public void attachFloorArchive(Long projectId, Long floorArchiveId) {
        int updated = repo.attachFloorArchiveIfAbsent(projectId, floorArchiveId);
        if (updated == 0) {
            log.warn("[attachFloorArchive] no-op: projectId={} (이미 attach 됨 or 존재 X)", projectId);
        }
    }

    @Transactional
    public void attachBrandManual(Long projectId, Long brandManualId) {
        int updated = repo.attachBrandManualIfAbsent(projectId, brandManualId);
        if (updated == 0) {
            log.warn("[attachBrandManual] no-op: projectId={} (이미 attach 됨 or 존재 X)", projectId);
        }
    }

    @Transactional
    public void attachFloorDetection(Long projectId, Long floorDetectionId) {
        int updated = repo.attachFloorDetectionIfAbsent(projectId, floorDetectionId);
        if (updated == 0) {
            log.warn("[attachFloorDetection] no-op: projectId={} (이미 attach 됨 or 존재 X)", projectId);
        }
    }

    /**
     * floor_detection_id 로 user_project 역추적.
     * 2026-04-29 신설: /place 호출 시 frontend 가 project_id 안 보내도 Java 가 자동 보강 (TR_D [데드존_위_설치] 후속 — ref_image S3 업로드 분기 정상화).
     */
    @Transactional(readOnly = true)
    public java.util.Optional<UserProject> findByFloorDetectionId(Long floorDetectionId) {
        if (floorDetectionId == null) return java.util.Optional.empty();
        return repo.findFirstByFloorDetectionId(floorDetectionId);
    }

    /**
     * floor_archive_id 로 user_project 역추적 (가장 최신).
     * 2026-04-29 신설: /space-data 호출 시 frontend 가 project_id 안 보내면 Java 가 자동 보강.
     * → space-data 완료 콜백에서 attachFloorDetection 정상 작동 → user_projects.floor_detection_id 채워짐
     * → 다음 /place 호출 시 findByFloorDetectionId 자동 보강도 작동 (chain 회복).
     * 같은 floor_archive_id 로 여러 project (재분석 등) 가능 — 가장 최신 1건만.
     */
    @Transactional(readOnly = true)
    public java.util.Optional<UserProject> findByFloorArchiveId(Long floorArchiveId) {
        if (floorArchiveId == null) return java.util.Optional.empty();
        return repo.findFirstByFloorArchiveIdOrderByIdDesc(floorArchiveId);
    }

    @Transactional
    public void attachPlacementResult(Long projectId, Long placementResultId) {
        UserProject p = getOrThrow(projectId);
        p.setPlacementResultId(placementResultId);
        repo.save(p);
    }

    @Transactional
    public void markDone(Long projectId) {
        UserProject p = getOrThrow(projectId);
        p.setStatus(UserProject.ProjectState.done);
        repo.save(p);
    }

    @Transactional
    public void markError(Long projectId) {
        UserProject p = getOrThrow(projectId);
        p.setStatus(UserProject.ProjectState.error);
        repo.save(p);
    }

    // ══════════════ 조회 ══════════════

    public List<UserProject> listByUser(Long userId) {
        return repo.findAllByUserIdOrderByCreatedAtDesc(userId).stream()
                .filter(p -> p.getDeletedAt() == null)
                .toList();
    }

    public UserProject getProject(Long projectId, Long userId) {
        UserProject p = getOrThrow(projectId);
        if (!p.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "project access denied");
        }
        return p;
    }

    public Map<String, Object> getProjectDetail(Long projectId, Long userId) {
        UserProject p = getProject(projectId, userId);
        Map<String, Object> out = new HashMap<>();
        out.put("id", p.getId());
        out.put("user_id", p.getUserId());
        out.put("name", p.getName());
        out.put("status", p.getStatus().name());
        out.put("stage", inferStage(p));
        out.put("floor_archive_id", p.getFloorArchiveId());
        out.put("brand_manual_id", p.getBrandManualId());
        out.put("floor_detection_id", p.getFloorDetectionId());
        out.put("placement_result_id", p.getPlacementResultId());
        out.put("created_at", p.getCreatedAt());
        out.put("updated_at", p.getUpdatedAt());

        if (p.getFloorArchiveId() != null) {
            floorArchiveRepo.findById(p.getFloorArchiveId()).ifPresent(archive -> {
                out.put("original_filename", archive.getOriginalFilename());
                out.put("pages_json", archive.getPagesJson()); // auto_detected 대체
            });
        }
        if (p.getBrandManualId() != null) {
            brandRepo.findById(p.getBrandManualId()).ifPresent(bm ->
                    out.put("brand_data_json", bm.getBrandDataJson()));
        }
        if (p.getFloorDetectionId() != null) {
            // 정본 SpaceData 병합 형식 (floor/entrance/reference_points/zone_map/dead_zones/main_artery).
            // 프론트가 spaceData.floor.polygon_mm 등 접근하므로 메타만 반환하면 안 됨.
            try {
                out.put("space_data", floorDetectionService.getAsSpaceData(p.getFloorDetectionId()));
            } catch (Exception e) {
                // 조회 실패 시 메타만 (기존 fallback)
                floorRepo.findById(p.getFloorDetectionId()).ifPresent(fd ->
                        out.put("space_data", floorToSpaceData(fd)));
            }
        }

        Long placementResultId = resolveLatestPlacementResultId(p);
        if (placementResultId != null) {
            out.put("layout_objects", loadLayoutObjects(placementResultId));
            out.put("placement_result_id", placementResultId); // p 에 없으면 체인 조회본으로 overwrite
            // 2026-05-04 신설 - sub_path / main_artery / ref_quality_score 응답에 포함.
            // walk_mm 노드가 b_space_data 에서 place 단계로 이동하면서 main_artery 가 placement_result 에 박힘.
            // sub_path - 여러 라인 형식 (각 가지 = 별 라인). 2026-05-04 형식 변경.
            // main_artery - 단일 라인 형식.
            // ref_quality_score - 디자인 참조 로직 트랙 8번 (모달 트리거용). 0.0 ~ 1.0 점수.
            try {
                placementResultRepo.findById(placementResultId).ifPresent(pr -> {
                    out.put("sub_path", deserializeJsonAny(pr.getSubPathJson()));
                    out.put("main_artery", deserializeJsonAny(pr.getMainArteryJson()));
                    out.put("ref_quality_score", pr.getRefQualityScore());
                });
            } catch (Exception e) {
                // deserialize 실패해도 응답 자체는 진행 - 시각화만 안 됨.
            }
        }
        return out;
    }

    /**
     * 2026-05-04 신설 - placement_result 의 sub_path_json / main_artery_json 컬럼을 임의 형식으로 deserialize.
     * sub_path = 여러 라인 List<List<List<Number>>>. main_artery = 단일 라인 List<List<Number>>.
     * Object 로 받아서 Jackson 이 자동 nested 처리. Spring 응답 시점 재직렬화.
     * null / 빈 문자열이면 null. 역직렬화 실패 시 null.
     */
    private static Object deserializeJsonAny(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return USER_PROJECT_OBJECT_MAPPER.readValue(json, Object.class);
        } catch (Exception e) {
            return null;
        }
    }

    private static final com.fasterxml.jackson.databind.ObjectMapper USER_PROJECT_OBJECT_MAPPER = new com.fasterxml.jackson.databind.ObjectMapper();

    /**
     * placement_result_id 우선순위: UserProject.placementResultId → floor_detection 최신 placement_result.
     */
    private Long resolveLatestPlacementResultId(UserProject p) {
        if (p.getPlacementResultId() != null) return p.getPlacementResultId();
        if (p.getFloorDetectionId() == null) return null;
        return placementResultRepo.findAllByFloorDetectionIdOrderByCreatedAtDesc(p.getFloorDetectionId())
                .stream()
                .findFirst()
                .map(PlacementResult::getId)
                .orElse(null);
    }

    /**
     * stage 분기 (프론트 progress UI용):
     *   error          — 실패
     *   done           — 배치 완료
     *   placing        — 배치 진행중 (placementResultId 존재 but 미완)
     *   place_ready    — floor_detection 완료 대기/시작
     *   space_ready    — floor_archive.pages_json 존재 (space_data 대기)
     *   detecting      — floor_archive 업로드 후 공간분석 대기
     *   init           — floor_archive 없음
     */
    private String inferStage(UserProject p) {
        if (p.getStatus() == UserProject.ProjectState.error) return "error";
        if (p.getStatus() == UserProject.ProjectState.done) return "done";

        if (resolveLatestPlacementResultId(p) != null) return "placing";
        if (p.getFloorDetectionId() != null) return "place_ready";
        if (p.getFloorArchiveId() != null) {
            FloorArchive archive = floorArchiveRepo.findById(p.getFloorArchiveId()).orElse(null);
            if (archive != null && archive.getPagesJson() != null && !archive.getPagesJson().isBlank()) return "space_ready";
            return "detecting";
        }
        return "init";
    }

    private Map<String, Object> floorToSpaceData(FloorDetection fd) {
        Map<String, Object> m = new HashMap<>();
        m.put("id", fd.getId());
        m.put("status", fd.getStatus() != null ? fd.getStatus().name() : null);
        m.put("scale_type", fd.getScaleType() != null ? fd.getScaleType().name() : null);
        m.put("venue_type", fd.getVenueType() != null ? fd.getVenueType().name() : null);
        m.put("scale_mm_per_px", fd.getScaleMmPerPx());
        m.put("detected_width_mm", fd.getDetectedWidthMm());
        m.put("detected_height_mm", fd.getDetectedHeightMm());
        m.put("usable_area_sqm", fd.getUsableAreaSqm());
        return m;
    }

    private List<Map<String, Object>> loadLayoutObjects(Long placementResultId) {
        List<PlacementObject> objects = placementObjectRepo.findAllByPlacementResultId(placementResultId);

        // floor_anchor_id → anchor_key 배치 조인 (N+1 회피).
        // 재배치 LLM 이 locked_objects 의 anchor_key 로 기존 위치를 판단하므로 필수.
        List<Long> anchorIds = objects.stream()
                .map(PlacementObject::getFloorAnchorId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, String> anchorKeyMap = anchorIds.isEmpty()
                ? Map.of()
                : floorAnchorRepo.findAllById(anchorIds).stream()
                    .collect(Collectors.toMap(FloorAnchor::getId, FloorAnchor::getAnchorKey));

        // 2026-05-01 Phase 4-2 — concept_area_id → name lookup (deep link 시 객체 색칠)
        List<Long> conceptIds = objects.stream()
                .map(PlacementObject::getConceptAreaId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, String> conceptNameMap = conceptIds.isEmpty()
                ? Map.of()
                : conceptAreaRepo.findAllById(conceptIds).stream()
                    .collect(Collectors.toMap(
                            com.landup.concept.ConceptArea::getId,
                            com.landup.concept.ConceptArea::getName));

        List<Map<String, Object>> out = new ArrayList<>();
        for (PlacementObject po : objects) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", po.getId());
            m.put("object_type", po.getObjectType());
            // 2026-05-10: layout_objects 에 누락됐던 필드 보강 (frontend Viewer3D / Result 표시용).
            m.put("label", po.getLabel());
            m.put("graphic_face", po.getGraphicFace());
            m.put("graphic_face_basis", po.getGraphicFaceBasis());
            m.put("category", po.getCategory());
            m.put("center_x_mm", po.getCenterXMm());
            m.put("center_y_mm", po.getCenterYMm());
            m.put("rotation_deg", po.getRotationDeg());
            m.put("width_mm", po.getWidthMm());
            m.put("depth_mm", po.getDepthMm());
            m.put("height_mm", po.getHeightMm());
            m.put("zone_label", po.getZoneLabel() != null ? po.getZoneLabel().name() : null);
            m.put("concept_area_id", po.getConceptAreaId());
            m.put("concept_area", po.getConceptAreaId() != null ? conceptNameMap.get(po.getConceptAreaId()) : null);
            m.put("direction", po.getDirection() != null ? po.getDirection().name() : null);
            m.put("alignment", po.getAlignment() != null ? po.getAlignment().name() : null);
            m.put("wall_attachment", po.getWallAttachment() != null ? po.getWallAttachment().name() : null);
            m.put("placed_because", po.getPlacedBecause());
            m.put("floor_anchor_id", po.getFloorAnchorId());
            m.put("anchor_key", po.getFloorAnchorId() != null ? anchorKeyMap.get(po.getFloorAnchorId()) : null);
            out.add(m);
        }
        return out;
    }

    @Transactional
    public UserProject rename(Long projectId, Long userId, String newName) {
        UserProject p = getProject(projectId, userId);
        p.setName(newName);
        return repo.save(p);
    }

    /**
     * 프로젝트 삭제 — 게이트 3 정책 (2026-04-27 결정).
     *
     * 라이프사이클 분리:
     *   - placement_results : 프로젝트 종속 → 명시 삭제 ✅
     *   - floor_detections, brand_manuals : 분석 자산 (영구) → 무관, retention cron 으로 별 처리
     *   - pdf : 박물관 trail (7일) → 무관, retention cron 으로 별 처리
     *   - ref_image : 시스템 공용 자산 → SET NULL (기존 정책 그대로)
     *
     * Java 명시 삭제 (갈래 2 부분 적용). DDL CASCADE (갈래 1) 는 1:N (분석 자산) 시나리오와
     * 충돌하므로 폐기. 자세한 결정 근거: 작업중/2026-04-26_프로젝트삭제_stale배지_및_cascade.md
     */
    @Transactional
    public void delete(Long projectId, Long userId) {
        UserProject p = getProject(projectId, userId);

        if (p.getPlacementResultId() != null) {
            placementResultRepo.deleteById(p.getPlacementResultId());
        }

        // soft delete — 완료 상태면 wasDone=true 기록 (플랜 한도 계산용)
        p.setWasDone(p.getStatus() == UserProject.ProjectState.done);
        p.setDeletedAt(LocalDateTime.now());
        repo.save(p);
    }

    private UserProject getOrThrow(Long projectId) {
        return repo.findById(projectId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "project not found: " + projectId));
    }

    // ══════════════ internal — worker 전용 조회 ══════════════

    /**
     * Python worker 재배치 시 이전 배치 오브젝트 조회.
     * user_id 소유자 검증 포함 — internal 망이 뚫려도 타인 데이터 노출 방지.
     */
    public List<Map<String, Object>> loadLatestLayoutObjectsForInternal(Long projectId, Long userId) {
        UserProject p = getProject(projectId, userId);
        Long placementResultId = resolveLatestPlacementResultId(p);
        if (placementResultId == null) return List.of();
        return loadLayoutObjects(placementResultId);
    }

    // ══════════════ internal 콜백용 FK 복원 ══════════════

    /** worker notify_java 에 FK 누락 시 project_id 로 user_projects 에서 복원. */
    public Long resolveFloorArchiveId(Long projectId) {
        if (projectId == null) return null;
        return repo.findById(projectId).map(UserProject::getFloorArchiveId).orElse(null);
    }

    public Long resolveBrandManualId(Long projectId) {
        if (projectId == null) return null;
        return repo.findById(projectId).map(UserProject::getBrandManualId).orElse(null);
    }

    public Long resolveFloorDetectionId(Long projectId) {
        if (projectId == null) return null;
        return repo.findById(projectId).map(UserProject::getFloorDetectionId).orElse(null);
    }

    // ══════════════ 내부 — 목록용 요약 ══════════════

    public List<Map<String, Object>> summarizeListForUser(Long userId) {
        List<UserProject> list = repo.findAllByUserIdOrderByCreatedAtDesc(userId).stream()
                .filter(p -> p.getDeletedAt() == null).toList();
        List<Map<String, Object>> out = new ArrayList<>();
        for (UserProject p : list) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", p.getId());
            m.put("user_id", p.getUserId());
            m.put("name", p.getName());
            m.put("status", p.getStatus().name());
            m.put("stage", inferStage(p));
            m.put("floor_archive_id", p.getFloorArchiveId());
            m.put("brand_manual_id", p.getBrandManualId());
            m.put("floor_detection_id", p.getFloorDetectionId());

            Long prId = resolveLatestPlacementResultId(p);
            m.put("placement_result_id", prId);
            m.put("has_layout", prId != null && !placementObjectRepo.findAllByPlacementResultId(prId).isEmpty());
            m.put("created_at", p.getCreatedAt());
            m.put("updated_at", p.getUpdatedAt());
            if (p.getFloorArchiveId() != null) {
                Optional<FloorArchive> archiveOpt = floorArchiveRepo.findById(p.getFloorArchiveId());
                m.put("original_filename", archiveOpt.map(FloorArchive::getOriginalFilename).orElse(null));
            } else {
                m.put("original_filename", null);
            }
            out.add(m);
        }
        return out;
    }
}
