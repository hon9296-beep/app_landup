package com.landup.placement;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/placements/failed-objects")
@RequiredArgsConstructor
public class PlacementFailedObjectController {

    private final PlacementFailedObjectService service;

    @GetMapping
    public List<PlacementFailedObject> list(@RequestParam("placement_result_id") Long placementResultId) {
        return service.listByResult(placementResultId);
    }

    @GetMapping("/by-type")
    public List<PlacementFailedObject> listByType(@RequestParam("object_type") String objectType) {
        return service.listByType(objectType);
    }
}
