package com.landup.concept;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ConceptAreaRepository extends JpaRepository<ConceptArea, Long> {

    /** floor_detection 의 모든 영역 조회 (concept_area.py 결정 결과 일괄). */
    List<ConceptArea> findAllByFloorDetectionId(Long floorDetectionId);

    /** floor_detection + name 으로 단건 조회 — 재분석 시 기존 영역 재사용 판단용. */
    Optional<ConceptArea> findFirstByFloorDetectionIdAndName(Long floorDetectionId, String name);
}
