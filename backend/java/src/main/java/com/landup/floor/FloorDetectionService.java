package com.landup.floor;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * FloorDetection + 하위 5종 일괄 처리 — 기존 PlacementDbService.saveFloorDetection 흡수.
 *
 * 신 스키마 변환:
 *   - floor_detections: pdf_page_id 단일 FK → pdf_id + page_number → floor_archive_id + page_number (2026-04-27)
 *   - result_json 컬럼 폐기 → 상위 컬럼(scale/venue/usable_*) + 하위 5종 테이블로 정규화
 *     · floor_points (main_door/emergency_exit/sprinkler/fire_hydrant/electrical_panel)
 *     · floor_polygons (inaccessible/dead_zone)
 *     · floor_anchors (reference points)
 *     · floor_zones (entrance/mid/deep zone polygons)
 *     ~~floor_main_artery (deprecated 2026-05-08)~~ — walk_mm 노드가 5/4 이후 placement 단계로 이동.
 *       main_artery 는 placement_results.main_artery_json 에 박힘. 옛 테이블/엔티티 코드 제거.
 *   - saveFloorDetection → applySpaceDataResult (하위 INSERT 포함)
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FloorDetectionService {

    private final FloorDetectionRepository floorRepo;
    private final FloorPointRepository pointRepo;
    private final FloorPolygonRepository polygonRepo;
    private final FloorAnchorRepository anchorRepo;
    private final FloorZoneRepository zoneRepo;
    // arteryRepo 제거 (2026-05-08) — walk_mm 이 placement 단계로 이동 후 floor_main_artery 미사용.
    private final com.landup.concept.ConceptAreaRepository conceptAreaRepo;  // 2026-05-01 Phase 4-2
    private final ObjectMapper objectMapper;

    // ══════════════ space_data worker 결과 반영 ══════════════

    /**
     * request: {floor_archive_id, page_number, brand_manual_id}
     * result:  worker 가 보낸 space_data payload
     *          (scale_type, venue_type, usable_poly_json, scale_mm_per_px, detected_*, usable_area_sqm,
     *           points[], polygons[], anchors[], zones[]) — main_artery 는 placement 단계로 이동 (2026-05-04)
     */
    @Transactional
    public Long applySpaceDataResult(Map<String, Object> request, Map<String, Object> result) {
        try {
            Object rawScaleType = result.get("scale_type");
            if (rawScaleType == null || rawScaleType.toString().isBlank()) {
                throw new ApiException(HttpStatus.BAD_REQUEST,
                        "space_data result missing scale_type (required: large|small|outdoor)");
            }
            FloorDetection.ScaleType scaleType;
            try {
                // 2026-05-04 (M2 fix) - 대소문자 민감 → toLowerCase 정규화. "Small" / "SMALL" 들어와도 enum 매칭.
                scaleType = FloorDetection.ScaleType.valueOf(rawScaleType.toString().toLowerCase());
            } catch (IllegalArgumentException e) {
                throw new ApiException(HttpStatus.BAD_REQUEST,
                        "invalid scale_type: " + rawScaleType + " (allowed: large|small|outdoor)");
            }
            FloorDetection.VenueType venueType = parseEnum(
                    FloorDetection.VenueType.class, result.get("venue_type"), null);

            FloorDetection detection = FloorDetection.builder()
                    .floorArchiveId(toLong(request.get("floor_archive_id")))
                    .pageNumber(toInt(request.get("page_number"), 1))
                    .brandManualId(toLong(request.get("brand_manual_id")))
                    .status(FloorDetection.DetectionStatus.done)
                    .scaleMmPerPx(toFloat(result.get("scale_mm_per_px")))
                    .scaleConfirmed(Boolean.TRUE.equals(result.get("scale_confirmed")))
                    .detectedWidthMm(toFloat(result.get("detected_width_mm")))
                    .detectedHeightMm(toFloat(result.get("detected_height_mm")))
                    .ceilingHeightMm(toFloat(result.get("ceiling_height_mm")))
                    .usableAreaSqm(toFloat(result.get("usable_area_sqm")))
                    .scaleType(scaleType)
                    .venueType(venueType)
                    .usablePolyJson(asJsonString(result.get("usable_poly_json")))
                    .build();
            floorRepo.save(detection);

            Long floorId = detection.getId();
            insertPoints(floorId, asList(result.get("points")));
            insertPolygons(floorId, asList(result.get("polygons")));
            insertAnchors(floorId, asList(result.get("anchors")), scaleType);
            insertZones(floorId, asList(result.get("zones")));
            // insertMainArtery 제거 (2026-05-08) — walk_mm 이 placement 단계로 이동 후 빈 호출이라 polluting noise.

            log.info("[DB] floor_detections INSERT (id={}, floorArchiveId={}, page={})",
                    floorId, detection.getFloorArchiveId(), detection.getPageNumber());
            return floorId;
        } catch (Exception e) {
            log.warn("[DB] floor_detections 저장 실패: {}", e.getMessage());
            return null;
        }
    }

    // ══════════════ 조회 ══════════════

    public FloorDetection getOrThrow(Long id) {
        return floorRepo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "floor_detection not found: " + id));
    }

    /**
     * FloorDetection 상위 필드 + 하위 5종 전체 묶어 반환 (FloorDetectionController, PlacementQueryService 공용).
     */
    public Map<String, Object> getFullDetail(Long id) {
        FloorDetection fd = getOrThrow(id);
        Map<String, Object> out = new HashMap<>();
        out.put("id", fd.getId());
        out.put("floor_archive_id", fd.getFloorArchiveId());
        out.put("page_number", fd.getPageNumber());
        out.put("brand_manual_id", fd.getBrandManualId());
        out.put("status", fd.getStatus() != null ? fd.getStatus().name() : null);
        out.put("scale_type", fd.getScaleType() != null ? fd.getScaleType().name() : null);
        out.put("venue_type", fd.getVenueType() != null ? fd.getVenueType().name() : null);
        out.put("scale_mm_per_px", fd.getScaleMmPerPx());
        out.put("scale_confirmed", fd.getScaleConfirmed());
        out.put("detected_width_mm", fd.getDetectedWidthMm());
        out.put("detected_height_mm", fd.getDetectedHeightMm());
        out.put("ceiling_height_mm", fd.getCeilingHeightMm());
        out.put("usable_area_sqm", fd.getUsableAreaSqm());
        out.put("usable_poly_json", fd.getUsablePolyJson());
        out.put("created_at", fd.getCreatedAt());
        out.put("points", pointRepo.findAllByFloorDetectionId(id));
        out.put("polygons", polygonRepo.findAllByFloorDetectionId(id));
        out.put("anchors", anchorRepo.findAllByFloorDetectionId(id));
        out.put("zones", zoneRepo.findAllByFloorDetectionId(id));
        // main_artery 제거 (2026-05-08) — placement_results.main_artery_json 으로 이동.
        return out;
    }

    public List<FloorDetection> listByFloorArchive(Long floorArchiveId) {
        return floorRepo.findAllByFloorArchiveIdOrderByPageNumberAsc(floorArchiveId);
    }

    // ══════════════ 프론트 SpaceData 병합 조회 ══════════════

    /**
     * 정규화 저장된 floor_detection 을 프론트 SpaceData 병합 형식으로 변환.
     * Python `_serialize_space_data` 와 동일 구조를 Java 측에서 재구성.
     */
    public Map<String, Object> getAsSpaceData(Long id) {
        FloorDetection fd = getOrThrow(id);
        List<FloorPoint> points = pointRepo.findAllByFloorDetectionId(id);
        List<FloorPolygon> polygons = polygonRepo.findAllByFloorDetectionId(id);
        List<FloorAnchor> anchors = anchorRepo.findAllByFloorDetectionId(id);
        List<FloorZone> zones = zoneRepo.findAllByFloorDetectionId(id);
        // FloorMainArtery 제거 (2026-05-08) — placement_results.main_artery_json 으로 이동.

        // 2026-05-01 Phase 4-2 — concept_area_id → name lookup (deep link 시 색칠 정보 응답)
        List<com.landup.concept.ConceptArea> conceptAreas = conceptAreaRepo.findAllByFloorDetectionId(id);
        Map<Long, String> conceptIdToName = conceptAreas.stream()
                .collect(java.util.stream.Collectors.toMap(
                        com.landup.concept.ConceptArea::getId,
                        com.landup.concept.ConceptArea::getName));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("_scale_type", fd.getScaleType() != null ? fd.getScaleType().name() : null);
        out.put("scale_type", fd.getScaleType() != null ? fd.getScaleType().name() : null);
        out.put("scale_mm_per_px", fd.getScaleMmPerPx());
        out.put("detected_width_mm", fd.getDetectedWidthMm());
        out.put("detected_height_mm", fd.getDetectedHeightMm());
        out.put("ceiling_height_mm", fd.getCeilingHeightMm());
        out.put("venue_type", fd.getVenueType() != null ? fd.getVenueType().name() : null);
        out.put("floor", buildFloor(fd));
        out.put("entrance", buildEntrance(points));
        out.put("reference_points", buildReferencePoints(anchors, conceptIdToName));
        out.put("zone_map", buildZoneMap(zones, anchors));
        out.put("concept_areas", buildConceptAreas(conceptAreas));  // 2026-05-01 Phase 4-2 갈래 3 — 폴리곤 채우기 + 레전드용
        out.put("dead_zones", buildDeadZones(polygons));
        // main_artery 제거 (2026-05-08) — placement_results.main_artery_json 으로 이동.
        // 프론트 Viewer3D 는 placementResult.main_artery 를 사용 (Viewer3D.tsx:782).
        // entrance_line 제거: walk_mm 노드 내부 계산용이며 프론트 미사용.
        out.put("sprinklers_mm", buildPointCoords(points, FloorPoint.PointType.sprinkler));
        out.put("hydrants_mm", buildPointCoords(points, FloorPoint.PointType.fire_hydrant));
        out.put("electric_panels_mm", buildPointCoords(points, FloorPoint.PointType.electrical_panel));
        return out;
    }

    // ── build helpers ──

    private Map<String, Object> buildFloor(FloorDetection fd) {
        Map<String, Object> floor = new HashMap<>();
        List<List<Double>> polygonMm = parsePolygonCoords(fd.getUsablePolyJson());
        floor.put("polygon_mm", polygonMm);
        floor.put("usable_area_sqm", fd.getUsableAreaSqm() != null ? fd.getUsableAreaSqm() : 0);
        long maxObjectWMm = 0;
        if (polygonMm != null && polygonMm.size() >= 3) {
            double minX = Double.MAX_VALUE, maxX = -Double.MAX_VALUE;
            double minY = Double.MAX_VALUE, maxY = -Double.MAX_VALUE;
            for (List<Double> c : polygonMm) {
                minX = Math.min(minX, c.get(0));
                maxX = Math.max(maxX, c.get(0));
                minY = Math.min(minY, c.get(1));
                maxY = Math.max(maxY, c.get(1));
            }
            maxObjectWMm = Math.round(Math.min(maxX - minX, maxY - minY) * 0.4);
        }
        floor.put("max_object_w_mm", maxObjectWMm);
        return floor;
    }

    private Map<String, Object> buildEntrance(List<FloorPoint> points) {
        Map<String, Object> entrance = new HashMap<>();
        entrance.put("x_mm", 0);
        entrance.put("y_mm", 0);
        if (points == null) return entrance;
        points.stream()
                .filter(p -> p.getType() == FloorPoint.PointType.main_door)
                .min(Comparator.comparing(FloorPoint::getId))
                .ifPresent(p -> {
                    entrance.put("x_mm", Math.round(p.getXMm()));
                    entrance.put("y_mm", Math.round(p.getYMm()));
                });
        return entrance;
    }

    private Map<String, Map<String, Object>> buildReferencePoints(
            List<FloorAnchor> anchors,
            Map<Long, String> conceptIdToName  // 2026-05-01 Phase 4-2 — concept_area_id → 영문 name
    ) {
        Map<String, Map<String, Object>> out = new LinkedHashMap<>();
        if (anchors == null) return out;
        for (FloorAnchor a : anchors) {
            Map<String, Object> rp = new HashMap<>();
            rp.put("x_mm", a.getXMm() != null ? Math.round(a.getXMm()) : 0);
            rp.put("y_mm", a.getYMm() != null ? Math.round(a.getYMm()) : 0);
            rp.put("zone_label", a.getZoneLabel() != null ? a.getZoneLabel().name() : null);
            // 2026-05-01 Phase 4-2 — concept_area name (영문) — 프론트 색칠용
            rp.put("concept_area_id", a.getConceptAreaId());
            rp.put("concept_area", a.getConceptAreaId() != null
                    ? conceptIdToName.get(a.getConceptAreaId()) : null);
            float wallLen = a.getWallLengthMm() != null ? a.getWallLengthMm() : 0f;
            String wallLabel = wallLen > 2000 ? "넓은 벽" : wallLen > 1000 ? "보통 벽" : "좁은 벽";
            rp.put("wall_size_label", wallLabel);
            String label = a.getLabel() != null ? a.getLabel() : "";
            rp.put("facing_entrance", "deep_wall".equals(label));
            rp.put("is_entrance_wall", "entrance_adjacent".equals(label));
            rp.put("is_partition", "inner_wall".equals(label));
            rp.put("walk_mm", a.getWalkMm() != null ? a.getWalkMm() : 0);
            out.put(a.getAnchorKey(), rp);
        }
        return out;
    }

    private Map<String, Map<String, Object>> buildZoneMap(List<FloorZone> zones, List<FloorAnchor> anchors) {
        Map<String, FloorZone> byLabel = new HashMap<>();
        if (zones != null) {
            for (FloorZone z : zones) {
                if (z.getZoneLabel() != null) byLabel.put(z.getZoneLabel().name(), z);
            }
        }
        Map<String, Map<String, Object>> out = new LinkedHashMap<>();
        for (String zname : Arrays.asList("entrance_zone", "mid_zone", "deep_zone")) {
            Map<String, Object> info = new HashMap<>();
            FloorZone z = byLabel.get(zname);
            info.put("polygon_mm", z != null ? parsePolygonCoords(z.getPolygonJson()) : new ArrayList<>());
            info.put("slot_count", 0);  // DB 미저장
            List<String> rpIds = new ArrayList<>();
            if (anchors != null) {
                for (FloorAnchor a : anchors) {
                    if (a.getZoneLabel() != null && a.getZoneLabel().name().equals(zname)) {
                        rpIds.add(a.getAnchorKey());
                    }
                }
            }
            info.put("reference_points", rpIds);
            info.put("walk_mm_range", new ArrayList<>());
            out.put(zname, info);
        }
        return out;
    }

    /**
     * 2026-05-01 Phase 4-2 갈래 3 — concept_areas 응답 (deep link 색칠 + 레전드용).
     * Python serialize_space_data 와 동일 형식: [{name(EN), polygon_mm, area_ratio}, ...]
     * 한국어 라벨은 프론트 CONCEPT_AREA_LABEL_KO 매핑 dict 로 변환.
     */
    private List<Map<String, Object>> buildConceptAreas(List<com.landup.concept.ConceptArea> areas) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (areas == null) return out;
        for (com.landup.concept.ConceptArea a : areas) {
            List<List<Double>> polygonMm = parsePolygonCoords(a.getPolygonJson());
            if (polygonMm == null || polygonMm.size() < 3) continue;
            Map<String, Object> entry = new HashMap<>();
            entry.put("name", a.getName());
            entry.put("polygon_mm", polygonMm);
            entry.put("area_ratio", a.getAreaRatio() != null ? a.getAreaRatio() : 0f);
            out.add(entry);
        }
        return out;
    }

    private List<Map<String, Object>> buildDeadZones(List<FloorPolygon> polygons) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (polygons == null) return out;
        for (FloorPolygon p : polygons) {
            if (p.getKind() != FloorPolygon.Kind.dead_zone) continue;
            Map<String, Object> dz = new HashMap<>();
            dz.put("type", p.getSource() != null ? p.getSource() : "unknown");
            List<List<Double>> polygonMm = parsePolygonCoords(p.getPolygonJson());
            dz.put("polygon_mm", polygonMm);
            double cx = p.getCenterXMm() != null ? p.getCenterXMm() : 0;
            double cy = p.getCenterYMm() != null ? p.getCenterYMm() : 0;
            long radius = p.getRadiusMm() != null ? Math.round(p.getRadiusMm()) : 0;
            dz.put("center_mm", List.of(Math.round(cx), Math.round(cy)));
            dz.put("radius_mm", radius);
            out.add(dz);
        }
        return out;
    }

    // buildLinestring 제거 (2026-05-08) — FloorMainArtery 옛 entity 와 함께 삭제됨.

    private List<List<Long>> buildPointCoords(List<FloorPoint> points, FloorPoint.PointType type) {
        List<List<Long>> out = new ArrayList<>();
        if (points == null) return out;
        for (FloorPoint p : points) {
            if (p.getType() == type) {
                out.add(List.of(
                        (long) Math.round(p.getXMm()),
                        (long) Math.round(p.getYMm())
                ));
            }
        }
        return out;
    }

    /** JSON 문자열 → [[x,y],...]. 좌표 배열 또는 GeoJSON {coordinates} 모두 대응. */
    private List<List<Double>> parsePolygonCoords(String json) {
        if (json == null || json.isBlank()) return new ArrayList<>();
        try {
            String trimmed = json.trim();
            if (trimmed.startsWith("[[")) {
                return objectMapper.readValue(json, new TypeReference<List<List<Double>>>() {});
            }
            JsonNode root = objectMapper.readTree(json);
            JsonNode coords = root.get("coordinates");
            if (coords == null) return new ArrayList<>();
            // Polygon 의 경우 외곽 ring 이 한 번 더 감싸져 있을 수 있음
            if (coords.isArray() && coords.size() > 0 && coords.get(0).isArray()
                    && coords.get(0).size() > 0 && coords.get(0).get(0).isArray()) {
                return objectMapper.convertValue(coords.get(0), new TypeReference<List<List<Double>>>() {});
            }
            return objectMapper.convertValue(coords, new TypeReference<List<List<Double>>>() {});
        } catch (Exception e) {
            log.warn("[floor] JSON 파싱 실패: {}", e.getMessage());
            return new ArrayList<>();
        }
    }

    public Long getLatestFloorDetectionId() {
        return floorRepo.findTopByOrderByIdDesc()
                .map(FloorDetection::getId)
                .orElse(null);
    }

    // ══════════════ 내부 — 하위 테이블 INSERT ══════════════

    private void insertPoints(Long floorId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            pointRepo.save(FloorPoint.builder()
                    .floorDetectionId(floorId)
                    .type(parseEnum(FloorPoint.PointType.class, r.get("type"), FloorPoint.PointType.main_door))
                    .xMm(toFloat(r.get("x_mm")))
                    .yMm(toFloat(r.get("y_mm")))
                    .widthMm(toFloat(r.get("width_mm")))
                    .isMain((Boolean) r.get("is_main"))
                    .build());
        }
    }

    private void insertPolygons(Long floorId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            polygonRepo.save(FloorPolygon.builder()
                    .floorDetectionId(floorId)
                    .kind(parseEnum(FloorPolygon.Kind.class, r.get("kind"), FloorPolygon.Kind.inaccessible))
                    .source(asString(r.get("source"), "unknown"))
                    .polygonJson(asJsonString(r.get("polygon_json")))
                    .centerXMm(toFloat(r.get("center_x_mm")))
                    .centerYMm(toFloat(r.get("center_y_mm")))
                    .radiusMm(toFloat(r.get("radius_mm")))
                    .build());
        }
    }

    private void insertAnchors(Long floorId, List<Map<String, Object>> rows, FloorDetection.ScaleType scaleType) {
        FloorAnchor.Scale scale = switch (scaleType) {
            case large -> FloorAnchor.Scale.large;
            case small -> FloorAnchor.Scale.small;
            case outdoor -> FloorAnchor.Scale.outdoor;
        };
        for (Map<String, Object> r : rows) {
            anchorRepo.save(FloorAnchor.builder()
                    .floorDetectionId(floorId)
                    .scale(scale)
                    .anchorKey(asString(r.get("anchor_key"), ""))
                    .xMm(toFloat(r.get("x_mm")))
                    .yMm(toFloat(r.get("y_mm")))
                    .wallNormal(parseEnum(FloorAnchor.WallNormal.class, r.get("wall_normal"), null))
                    .wallAngleDeg(toFloat(r.get("wall_angle_deg")))
                    .wallLengthMm(toFloat(r.get("wall_length_mm")))
                    .label(asString(r.get("label"), null))
                    .zoneLabel(parseEnum(FloorAnchor.ZoneLabel.class, r.get("zone_label"), null))
                    .conceptAreaId(toLong(r.get("concept_area_id")))
                    .walkMm(toFloat(r.get("walk_mm")))
                    .shelfCapacity(toInt(r.get("shelf_capacity"), null))
                    .build());
        }
    }

    private void insertZones(Long floorId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            zoneRepo.save(FloorZone.builder()
                    .floorDetectionId(floorId)
                    .zoneLabel(parseEnum(FloorZone.ZoneLabel.class, r.get("zone_label"), FloorZone.ZoneLabel.mid_zone))
                    .polygonJson(asJsonString(r.get("polygon_json")))
                    .build());
        }
    }

    // insertMainArtery 제거 (2026-05-08) — FloorMainArtery 옛 entity 와 함께 삭제됨.

    // ══════════════ 타입 유틸 ══════════════

    private Long toLong(Object val) {
        if (val == null) return null;
        if (val instanceof Number n) return n.longValue();
        try { return Long.parseLong(val.toString()); } catch (Exception e) { return null; }
    }

    private Integer toInt(Object val, Integer fb) {
        if (val == null) return fb;
        if (val instanceof Number n) return n.intValue();
        try { return Integer.parseInt(val.toString()); } catch (Exception e) { return fb; }
    }

    private Float toFloat(Object val) {
        if (val == null) return null;
        if (val instanceof Number n) return n.floatValue();
        try { return Float.parseFloat(val.toString()); } catch (Exception e) { return null; }
    }

    private String asString(Object val, String fb) {
        return val == null ? fb : val.toString();
    }

    private String asJsonString(Object val) {
        if (val == null) return null;
        if (val instanceof String s) return s;
        try { return objectMapper.writeValueAsString(val); }
        catch (Exception e) { return val.toString(); }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> asList(Object val) {
        if (val instanceof List<?> l) return (List<Map<String, Object>>) l;
        return new ArrayList<>();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object val) {
        if (val instanceof Map<?, ?> m) return (Map<String, Object>) m;
        return null;
    }

    private static <E extends Enum<E>> E parseEnum(Class<E> cls, Object val, E fb) {
        if (val == null) return fb;
        try { return Enum.valueOf(cls, val.toString()); }
        catch (IllegalArgumentException e) { return fb; }
    }
}
