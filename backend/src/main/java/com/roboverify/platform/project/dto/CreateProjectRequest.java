package com.roboverify.platform.project.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record CreateProjectRequest(

        @NotBlank(message = "项目名不能为空")
        @Size(max = 128, message = "项目名长度不能超过 128")
        String name,

        @Size(max = 1024, message = "描述长度不能超过 1024")
        String description
) {
}
