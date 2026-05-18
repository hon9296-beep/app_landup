package com.landup.job;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * LLM 비용 집계 — placement_result × node 단위.
 * Python worker 가 /internal/token-usage 로 노드별 토큰량 POST.
 */
@Service
@RequiredArgsConstructor
public class TokenUsageService {

    private final TokenUsageRepository repo;

    public List<TokenUsage> listByResult(Long placementResultId) {
        return repo.findAllByPlacementResultId(placementResultId);
    }

    @Transactional
    public TokenUsage upsert(TokenUsage incoming) {
        return repo.findByPlacementResultIdAndNodeName(incoming.getPlacementResultId(), incoming.getNodeName())
                .map(existing -> {
                    existing.setInputTokens(incoming.getInputTokens());
                    existing.setOutputTokens(incoming.getOutputTokens());
                    existing.setCacheReadTokens(incoming.getCacheReadTokens());
                    existing.setCacheWriteTokens(incoming.getCacheWriteTokens());
                    existing.setModel(incoming.getModel());
                    return repo.save(existing);
                })
                .orElseGet(() -> repo.save(incoming));
    }

    /** 결과별 합산. */
    public Map<String, Long> sumByResult(Long placementResultId) {
        List<TokenUsage> rows = repo.findAllByPlacementResultId(placementResultId);
        long input = rows.stream().mapToLong(TokenUsage::getInputTokens).sum();
        long output = rows.stream().mapToLong(TokenUsage::getOutputTokens).sum();
        long cacheRead = rows.stream().mapToLong(TokenUsage::getCacheReadTokens).sum();
        long cacheWrite = rows.stream().mapToLong(TokenUsage::getCacheWriteTokens).sum();
        Map<String, Long> sum = new HashMap<>();
        sum.put("input_tokens", input);
        sum.put("output_tokens", output);
        sum.put("cache_read_tokens", cacheRead);
        sum.put("cache_write_tokens", cacheWrite);
        sum.put("total", input + output + cacheRead + cacheWrite);
        return sum;
    }
}
