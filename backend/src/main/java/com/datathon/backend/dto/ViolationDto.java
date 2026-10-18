package com.datathon.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = true)
public class ViolationDto {
    private String type;

    @JsonProperty("timecode_sec")
    private Double timecodeSec;

    @JsonProperty("start_sec")
    private Double startSec;

    @JsonProperty("end_sec")
    private Double endSec;

    @JsonProperty("category_id")
    private String categoryId;

    private String localization;
    private String status;

    private String description;

    @JsonProperty("evidence_frames")
    private List<EvidenceFrameDto> evidenceFrames;

    private RuleDto rule;
}
