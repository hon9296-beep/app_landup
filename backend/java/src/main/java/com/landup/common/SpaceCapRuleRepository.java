package com.landup.common;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface SpaceCapRuleRepository extends JpaRepository<SpaceCapRule, Long> {
    Optional<SpaceCapRule> findByScopeAndKeyName(String scope, String keyName);
    List<SpaceCapRule> findAllByScopeAndKeyKind(String scope, SpaceCapRule.KeyKind keyKind);
}
