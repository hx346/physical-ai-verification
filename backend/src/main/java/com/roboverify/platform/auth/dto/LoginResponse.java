package com.roboverify.platform.auth.dto;

public record LoginResponse(String token, String username, String role) {
}
