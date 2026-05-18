package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@RequiredArgsConstructor
public class SpaceCapRuleService {

    private final SpaceCapRuleRepository repo;

    public List<SpaceCapRule> listByScopeAndKind(String scope, SpaceCapRule.KeyKind keyKind) {
        return repo.findAllByScopeAndKeyKind(scope, keyKind);
    }

    public SpaceCapRule get(String scope, String keyName) {
        return repo.findByScopeAndKeyName(scope, keyName)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND,
                        "space_cap_rule not found: " + scope + "/" + keyName));
    }
}
