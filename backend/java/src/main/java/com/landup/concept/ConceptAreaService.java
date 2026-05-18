package com.landup.concept;

import com.landup.concept.dto.ConceptAreaCreateBatchRequest;
import com.landup.concept.dto.ConceptAreaCreateRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 컨셉 영역 영속 + 조회 (2026-05-01 신설).
 *
 * Python concept_area.py 가 LLM 결정 후 batch INSERT 호출 → 응답으로 {name: id} 반환.
 * 응답 dict 의 id 를 Python state 가 참조하여 placement.py 가 placement_objects.concept_area_id FK 채움.
 *
 * 정책: 같은 (floor_detection_id, name) 재호출 시 추가 INSERT (UNIQUE 제약 X) — 재분석 시나리오 보존.
 */
@Service
@RequiredArgsConstructor
public class ConceptAreaService {

    private final ConceptAreaRepository repo;

    /**
     * batch INSERT — 한 사이클의 영역 일괄 영속.
     *
     * @return {name → id} dict. Python 이 이 dict 로 state.concept_areas[i].id 채움.
     *         여러 영역의 name 이 같으면 (이론상 일어나면 안 됨) 마지막 id 가 dict 에 남음.
     */
    @Transactional
    public Map<String, Long> createBatch(ConceptAreaCreateBatchRequest req) {
        List<ConceptArea> entities = req.getAreas().stream()
            .map(a -> toEntity(req.getFloorDetectionId(), a))
            .collect(Collectors.toList());

        List<ConceptArea> saved = repo.saveAll(entities);

        // LinkedHashMap — 입력 순서 보존 (동명 영역 시 나중 id 가 덮어쓰지만 일반적이지 않음)
        Map<String, Long> nameToId = new LinkedHashMap<>();
        for (ConceptArea ca : saved) {
            nameToId.put(ca.getName(), ca.getId());
        }
        return nameToId;
    }

    @Transactional(readOnly = true)
    public List<ConceptArea> listByFloorDetection(Long floorDetectionId) {
        return repo.findAllByFloorDetectionId(floorDetectionId);
    }

    private ConceptArea toEntity(Long floorDetectionId, ConceptAreaCreateRequest req) {
        return ConceptArea.builder()
            .floorDetectionId(floorDetectionId)
            .name(req.getName())
            .polygonJson(req.getPolygonJson())
            .areaRatio(req.getAreaRatio())
            .targetObjectsJson(req.getTargetObjectsJson())
            .build();
    }
}
