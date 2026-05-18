package com.landup.placement;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

/**
 * 배치 실패 오브젝트 전담 — 조회 + applyPlaceResult 시 bulk INSERT.
 * 프론트 "배치 리포트" 패널에서 사용.
 */
@Service
@RequiredArgsConstructor
public class PlacementFailedObjectService {

    private final PlacementFailedObjectRepository repo;

    @Transactional
    public void insertBatch(Long placementResultId, List<Map<String, Object>> rows) {
        for (Map<String, Object> r : rows) {
            repo.save(PlacementFailedObject.builder()
                    .placementResultId(placementResultId)
                    .objectType(asString(r.get("object_type"), "unknown"))
                    .reason(asString(r.get("reason"), "unknown"))
                    .build());
        }
    }

    public List<PlacementFailedObject> listByResult(Long placementResultId) {
        return repo.findAllByPlacementResultId(placementResultId);
    }

    public List<PlacementFailedObject> listByType(String objectType) {
        return repo.findAllByObjectType(objectType);
    }

    private static String asString(Object o, String fb) { return o == null ? fb : o.toString(); }
}
