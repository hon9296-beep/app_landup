package com.landup.job;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface JobRepository extends JpaRepository<Job, Long> {
    List<Job> findAllByUserIdOrderByCreatedAtDesc(Long userId);
    List<Job> findAllByUserIdAndStatus(Long userId, Job.JobState status);
}
