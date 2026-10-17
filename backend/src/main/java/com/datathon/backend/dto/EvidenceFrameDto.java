package com.datathon.backend.entity;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class EvidenceFrameDto {
    @JsonProperty("timestamp_sec")
    private Double timestampSec;

    @JsonProperty("image_base64")
    private String imageBase64;
}