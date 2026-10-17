package com.datathon.backend.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class AnalyzeInitResponse {
    @JsonProperty("job_id")
    private String jobId;

    @Builder.Default
    private String status = "processing";

    @Builder.Default
    private String mode = "real";
}