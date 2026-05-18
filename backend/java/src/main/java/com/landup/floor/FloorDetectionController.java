package com.landup.floor;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * floor_detections 조회 엔드포인트.
 *
 * 신 스키마: result_json 컬럼 폐기. 상위 컬럼 + 하위 5종(points/polygons/anchors/zones/main_artery)
 *          묶어서 반환 — FloorDetectionService.getFullDetail 위임.
 *
 * 프론트/Python worker 가 space_data 재구성 시 이걸 호출.
 */
@RestController
@RequestMapping("/floor-detections")
@RequiredArgsConstructor
public class FloorDetectionController {

    private final FloorDetectionService service;

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable Long id) {
        // 프론트 getFloorDetectionResult 가 res.data.result 로 꺼내므로 wrapping.
        // 정규화 저장된 데이터를 SpaceData 병합 형식으로 변환.
        return Map.of("result", service.getAsSpaceData(id));
    }

    @GetMapping
    public List<FloorDetection> listByFloorArchive(@RequestParam("floor_archive_id") Long floorArchiveId) {
        return service.listByFloorArchive(floorArchiveId);
    }
}
