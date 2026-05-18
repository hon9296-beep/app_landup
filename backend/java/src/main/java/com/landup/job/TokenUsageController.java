package com.landup.job;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/token-usage")
@RequiredArgsConstructor
public class TokenUsageController {

    private final TokenUsageService service;

    @GetMapping
    public List<TokenUsage> list(@RequestParam("placement_result_id") Long placementResultId) {
        return service.listByResult(placementResultId);
    }

    @GetMapping("/sum")
    public Map<String, Long> sum(@RequestParam("placement_result_id") Long placementResultId) {
        return service.sumByResult(placementResultId);
    }

    /** Python worker 내부 콜백 — 노드 실행 종료 직후 토큰량 기록. */
    @PostMapping("/internal")
    public TokenUsage postInternal(@RequestBody TokenUsage body) {
        return service.upsert(body);
    }
}
