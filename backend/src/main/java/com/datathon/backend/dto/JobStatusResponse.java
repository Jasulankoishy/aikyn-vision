package com.datathon.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = true)
public class JobStatusResponse {
    @JsonProperty("job_id")
    private String jobId;

    private String status;      // "processing", "done", "failed"
    private String verdict;     // "violation", "no_violation"
    private String mode;        // "real"
    private List<ViolationDto> violations;
    private Map<String, Object> analysis;
    private Map<String, Object> error;
}