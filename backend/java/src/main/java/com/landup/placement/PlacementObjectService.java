package com.landup.placement;

import com.landup.common.ApiException;
import com.landup.floor.FloorAnchor;
import com.landup.floor.FloorAnchorRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * PlacementObject 전담 — 개별 편집 + applyPlaceResult 시 bulk INSERT.
 *
 * 신 스키마 변환:
 *   - 상위 FK: floor_detection_id → placement_result_id
 *   - furniture_standard_id 제거 → object_type(String) + floor_anchor_id(FK) 로 분리
 *   - label/pos_x_mm/pos_y_mm → object_type/center_x_mm/center_y_mm
 *
 * Q2-A 적용: Python worker 는 anchor_key(String) 를 보내고,
 *            Java 가 FloorAnchorRepository.findByFloorDetectionIdAndAnchorKey 로 Long FK 로 변환.
 */
@Service
@RequiredArgsConstructor
public class PlacementObjectService {

    private final PlacementObjectRepository repo;
    private final FloorAnchorRepository floorAnchorRepo;

    // ══════════════ applyPlaceResult 위임 진입점 ══════════════

    @Transactional
    public void insertBatch(Long placementResultId, Long floorDetectionId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            Long floorAnchorId = resolveAnchorId(floorDetectionId, asString(r.get("anchor_key")));
            repo.save(PlacementObject.builder()
                    .placementResultId(placementResultId)
                    .objectType(asString(r.get("object_type"), "unknown"))
                    .label(asString(r.get("label")))
                    .floorAnchorId(floorAnchorId)
                    .centerXMm(asFloat(r.get("center_x_mm")))
                    .centerYMm(asFloat(r.get("center_y_mm")))
                    .rotationDeg(asFloat(r.getOrDefault("rotation_deg", 0f)))
                    .widthMm(asFloat(r.get("width_mm")))
                    .depthMm(asFloat(r.get("depth_mm")))
                    .heightMm(Optional.ofNullable(asFloat(r.get("height_mm"))).orElse(1500f))
                    .zoneLabel(asEnum(PlacementObject.ZoneLabel.class, r.get("zone_label"), null))
                    .conceptAreaId(asLong(r.get("concept_area_id")))
                    .direction(asEnum(PlacementObject.Direction.class, r.get("direction"), null))
                    .alignment(asEnum(PlacementObject.Alignment.class, r.get("alignment"), null))
                    .wallAttachment(asEnum(PlacementObject.WallAttachment.class, r.get("wall_attachment"), null))
                    .category(asString(r.get("category")))
                    .graphicFace(asString(r.get("graphic_face")))
                    .graphicFaceBasis(asString(r.get("graphic_face_basis")))
                    .placedBecause(asString(r.get("placed_because")))
                    .build());
        }
    }

    /** Python anchor_key(String) → FK Long 변환. 키가 없거나 매칭 실패 시 null. */
    private Long resolveAnchorId(Long floorDetectionId, String anchorKey) {
        if (anchorKey == null || anchorKey.isBlank() || floorDetectionId == null) return null;
        return floorAnchorRepo.findByFloorDetectionIdAndAnchorKey(floorDetectionId, anchorKey)
                .map(FloorAnchor::getId)
                .orElse(null);
    }

    // ══════════════ 개별 조회/편집 ══════════════

    public List<PlacementObject> listByResult(Long placementResultId) {
        return repo.findAllByPlacementResultId(placementResultId);
    }

    public PlacementObject getOrThrow(Long id) {
        return repo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "placement_object not found: " + id));
    }

    @Transactional
    public PlacementObject update(Long id, PlacementObject patch) {
        PlacementObject existing = getOrThrow(id);
        if (patch.getCenterXMm() != null) existing.setCenterXMm(patch.getCenterXMm());
        if (patch.getCenterYMm() != null) existing.setCenterYMm(patch.getCenterYMm());
        if (patch.getRotationDeg() != null) existing.setRotationDeg(patch.getRotationDeg());
        if (patch.getWidthMm() != null) existing.setWidthMm(patch.getWidthMm());
        if (patch.getDepthMm() != null) existing.setDepthMm(patch.getDepthMm());
        if (patch.getHeightMm() != null) existing.setHeightMm(patch.getHeightMm());
        if (patch.getZoneLabel() != null) existing.setZoneLabel(patch.getZoneLabel());
        if (patch.getDirection() != null) existing.setDirection(patch.getDirection());
        if (patch.getAlignment() != null) existing.setAlignment(patch.getAlignment());
        if (patch.getWallAttachment() != null) existing.setWallAttachment(patch.getWallAttachment());
        return repo.save(existing);
    }

    @Transactional
    public void delete(Long id) {
        if (!repo.existsById(id)) {
            throw new ApiException(HttpStatus.NOT_FOUND, "placement_object not found: " + id);
        }
        repo.deleteById(id);
    }

    // ══════════════ 타입 유틸 ══════════════

    private static String asString(Object o) { return o == null ? null : o.toString(); }
    private static String asString(Object o, String fb) { return o == null ? fb : o.toString(); }

    private static Float asFloat(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.floatValue();
        try { return Float.parseFloat(o.toString()); } catch (Exception e) { return null; }
    }

    private static Long asLong(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.longValue();
        try { return Long.parseLong(o.toString()); } catch (Exception e) { return null; }
    }

    private static <E extends Enum<E>> E asEnum(Class<E> cls, Object o, E fb) {
        if (o == null) return fb;
        try { return Enum.valueOf(cls, o.toString()); }
        catch (IllegalArgumentException e) { return fb; }
    }
}
