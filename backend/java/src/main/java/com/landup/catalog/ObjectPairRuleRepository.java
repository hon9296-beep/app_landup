package com.landup.catalog;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ObjectPairRuleRepository extends JpaRepository<ObjectPairRule, Long> {
    List<ObjectPairRule> findAllByObjectACode(String objectACode);
    List<ObjectPairRule> findAllBySource(ObjectPairRule.Source source);
}
