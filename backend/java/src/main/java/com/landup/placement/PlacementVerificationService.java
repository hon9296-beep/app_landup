package com.landup.placement;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

/**
 * PlacementVerification 전담 — 조회 + applyPlaceResult 시 bulk INSERT.
 */
@Service
@RequiredArgsConstructor
public class PlacementVerificationService {

    private final PlacementVerificationRepository repo;

    @Transactional
    public void insertBatch(Long placementResultId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            repo.save(PlacementVerification.builder()
                    .placementResultId(placementResultId)
                    .placementObjectId(asLong(r.get("placement_object_id")))
                    .rule(asEnum(PlacementVerification.Rule.class, r.get("rule"),
                            PlacementVerification.Rule.floor_exit))
                    .severity(asEnum(PlacementVerification.Severity.class, r.get("severity"),
                            PlacementVerification.Severity.warning))
                    .detail(asString(r.get("detail")))
                    .build());
        }
    }

    public List<PlacementVerification> listByResult(Long placementResultId) {
        return repo.findAllByPlacementResultId(placementResultId);
    }

    public List<PlacementVerification> listBlocking(Long placementResultId) {
        return repo.findAllByPlacementResultIdAndSeverity(placementResultId, PlacementVerification.Severity.blocking);
    }

    private static String asString(Object o) { return o == null ? null : o.toString(); }

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
