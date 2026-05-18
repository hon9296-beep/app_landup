package com.landup.placement;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

/**
 * space_cap 적용 로그 전담 — 조회 + applyPlaceResult 시 bulk INSERT.
 */
@Service
@RequiredArgsConstructor
public class PlacementCapLogService {

    private final PlacementCapLogRepository repo;

    @Transactional
    public void insertBatch(Long placementResultId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            repo.save(PlacementCapLog.builder()
                    .placementResultId(placementResultId)
                    .objectType(asString(r.get("object_type"), ""))
                    .dimension(asString(r.get("dimension"), ""))
                    .fromCount(asInt(r.get("from_count")))
                    .toCount(asInt(r.get("to_count")))
                    .reason(asString(r.get("reason"), ""))
                    .build());
        }
    }

    public List<PlacementCapLog> listByResult(Long placementResultId) {
        return repo.findAllByPlacementResultId(placementResultId);
    }

    private static String asString(Object o, String fb) { return o == null ? fb : o.toString(); }

    private static Integer asInt(Object o) {
        if (o == null) return 0;
        if (o instanceof Number n) return n.intValue();
        try { return Integer.parseInt(o.toString()); } catch (Exception e) { return 0; }
    }
}
