package com.datathon.backend.repository;

import com.datathon.backend.entity.JobEntity;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Repository
public interface JobRepository extends JpaRepository<JobEntity, String> {

    List<JobEntity> findByStatus(String status);

    @Modifying
    @Transactional
    @Query("delete from JobEntity j where j.createdAt < :cutoff")
    int deleteOlderThan(@Param("cutoff") long cutoff);
}