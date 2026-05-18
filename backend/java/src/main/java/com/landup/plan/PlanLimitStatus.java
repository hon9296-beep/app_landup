package com.landup.plan;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public class PlanLimitStatus {

    private String membership;

    private int usedProjects;
    private int maxProjects;

    private int usedRedeploys;
    private int maxRedeploys;

    private int usedConcurrent;
    private int maxConcurrent;

    private int creditBalance;

    public boolean isProjectsExceeded()   { return usedProjects   >= maxProjects;   }
    public boolean isRedeploysExceeded()  { return usedRedeploys  >= maxRedeploys;  }
    public boolean isConcurrentExceeded() { return usedConcurrent >= maxConcurrent; }

    public static PlanLimitStatus unlimited(String membership) {
        return new PlanLimitStatus(membership, 0, Integer.MAX_VALUE, 0, Integer.MAX_VALUE, 0, Integer.MAX_VALUE, 0);
    }
}
