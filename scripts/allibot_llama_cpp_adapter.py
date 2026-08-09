"""Prepare a pristine upstream AlliBot source tree for llama.cpp runtime calls."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


ADAPTER_VERSION = "llama-cpp-chat-v1"

CLIENT_SOURCE = """package ai.llm;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** llama.cpp OpenAI-compatible chat-completions client used only by AlliBot. */
public final class LlamaCppChatCompletion {
    private static final String BASE_URL = System.getenv().getOrDefault(
            "LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080");

    private LlamaCppChatCompletion() { }

    public static String complete(String model, String prompt, int connectTimeoutMs,
                                  int readTimeoutMs) throws Exception {
        JsonObject body = new JsonObject();
        body.addProperty("model", model);
        body.addProperty("stream", false);
        body.addProperty("temperature", 0.0);
        JsonObject message = new JsonObject();
        message.addProperty("role", "user");
        message.addProperty("content", prompt);
        JsonArray messages = new JsonArray();
        messages.add(message);
        body.add("messages", messages);

        URL url = new URL(normalizeBaseUrl() + "/v1/chat/completions");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setConnectTimeout(connectTimeoutMs);
        connection.setReadTimeout(readTimeoutMs);
        connection.setDoOutput(true);
        try (OutputStream output = connection.getOutputStream()) {
            output.write(body.toString().getBytes(StandardCharsets.UTF_8));
        }
        int status = connection.getResponseCode();
        InputStream stream = status == HttpURLConnection.HTTP_OK
                ? connection.getInputStream() : connection.getErrorStream();
        String response = readAll(stream);
        if (status != HttpURLConnection.HTTP_OK) {
            throw new IOException("llama.cpp chat-completions error (" + status + "): " + response);
        }
        JsonObject top = JsonParser.parseString(response).getAsJsonObject();
        JsonArray choices = top.getAsJsonArray("choices");
        if (choices != null && choices.size() > 0) {
            JsonObject choice = choices.get(0).getAsJsonObject();
            JsonObject assistant = choice.getAsJsonObject("message");
            if (assistant != null && assistant.has("content")) {
                String content = assistant.get("content").getAsString();
                if (!content.isEmpty()) return content;
            }
        }
        throw new IOException("No assistant message content in llama.cpp response");
    }

    private static String normalizeBaseUrl() {
        return BASE_URL.endsWith("/") ? BASE_URL.substring(0, BASE_URL.length() - 1) : BASE_URL;
    }

    private static String readAll(InputStream stream) throws IOException {
        if (stream == null) return "";
        StringBuilder text = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            for (String line; (line = reader.readLine()) != null; ) text.append(line);
        }
        return text.toString();
    }
}
"""


def prepare(upstream_source: Path, adapted_source: Path) -> None:
    """Copy pinned source then adapt the LLM code reachable from `alli` only."""
    if adapted_source.exists():
        shutil.rmtree(adapted_source)
    shutil.copytree(upstream_source, adapted_source)
    client = adapted_source / "ai" / "llm" / "LlamaCppChatCompletion.java"
    client.parent.mkdir(parents=True, exist_ok=True)
    client.write_text(CLIENT_SOURCE, encoding="utf-8")
    _adapt_search(adapted_source / "ai" / "mcts" / "llmguided" / "LLMInformedMCTS.java")
    _adapt_policy(adapted_source / "ai" / "stochastic" / "LLMPolicyProbabilityDistribution.java")
    _adapt_allibot(adapted_source / "ai" / "abstraction" / "submissions" / "allibot" / "alli.java")


def _rewrite(path: Path, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = path.read_text(encoding="utf-8")
    text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"Cannot apply the expected llama.cpp adapter fragment: {path}")
    path.write_text(text, encoding="utf-8")


def _adapt_search(path: Path) -> None:
    _rewrite(path, r"import ai\.core\.InterruptibleAI;", "import ai.core.InterruptibleAI;\nimport ai.llm.LlamaCppChatCompletion;")
    _rewrite(path, r"    private static final String OLLAMA_HOST =.*?System\.getenv\(\)\.getOrDefault\(\"OLLAMA_MODEL\", \"llama3\.1:8b\"\);", '    private static final String MODEL =\n            System.getenv().getOrDefault("LLAMA_CPP_MODEL", "qwen3.5-9b");', flags=re.DOTALL)
    _rewrite(path, r"    private String callOllamaAPI\(String prompt\) throws Exception \{.*?\n    \}(?=\n\n    /\*\*)", "    private String callLlamaCppAPI(String prompt) throws Exception {\n        return LlamaCppChatCompletion.complete(MODEL, prompt, 5000, 15000);\n    }", flags=re.DOTALL)
    _rewrite(path, r"callOllamaAPI\(prompt\)", "callLlamaCppAPI(prompt)")


def _adapt_policy(path: Path) -> None:
    _rewrite(path, r"package ai\.stochastic;", "package ai.stochastic;\n\nimport ai.llm.LlamaCppChatCompletion;")
    _rewrite(path, r"    private static final String OLLAMA_HOST =.*?System\.getenv\(\)\.getOrDefault\(\"OLLAMA_MODEL\", \"llama3\.1:8b\"\);", '    private static final String MODEL =\n            System.getenv().getOrDefault("LLAMA_CPP_MODEL", "qwen3.5-9b");', flags=re.DOTALL)
    _rewrite(path, r"    private String callOllamaAPI\(String prompt\) throws Exception \{.*?\n    \}(?=\n\n    /\*\*)", "    private String callLlamaCppAPI(String prompt) throws Exception {\n        return LlamaCppChatCompletion.complete(MODEL, prompt, 5000, 15000);\n    }", flags=re.DOTALL)
    _rewrite(path, r"callOllamaAPI\(prompt\)", "callLlamaCppAPI(prompt)")


def _adapt_allibot(path: Path) -> None:
    _rewrite(path, r"import ai\.core\.ParameterSpecification;", "import ai.core.ParameterSpecification;\nimport ai.llm.LlamaCppChatCompletion;")
    _rewrite(path, r"    // Search\+LLM configuration.*?    private static boolean SEARCH_ENV_WARNING_PRINTED = false;", '''    // Optional runtime guidance uses the local llama.cpp OpenAI-compatible endpoint.
    private static final boolean USE_SEARCH_LLM =
            Boolean.parseBoolean(System.getenv().getOrDefault("ALLI_USE_SEARCH_LLM", "true"));
    private static final int SEARCH_LLM_INTERVAL =
            Integer.parseInt(System.getenv().getOrDefault("ALLI_SEARCH_INTERVAL", "200"));
    private static final boolean USE_SMALL_MAP_LLM_ADVISOR =
            Boolean.parseBoolean(System.getenv().getOrDefault("ALLI_SMALLMAP_LLM_ADVISOR", "true"));
    private static final int SMALL_MAP_ADVISOR_INTERVAL =
            Integer.parseInt(System.getenv().getOrDefault("ALLI_SMALLMAP_LLM_INTERVAL", "350"));
    private static final int SMALL_MAP_ADVISOR_CONNECT_MS =
            Integer.parseInt(System.getenv().getOrDefault("ALLI_SMALLMAP_LLM_CONNECT_MS", "120"));
    private static final int SMALL_MAP_ADVISOR_READ_MS =
            Integer.parseInt(System.getenv().getOrDefault("ALLI_SMALLMAP_LLM_READ_MS", "900"));
    private static final String LLAMA_CPP_BASE_URL =
            System.getenv().getOrDefault("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080");
    private static final String LLAMA_CPP_MODEL =
            System.getenv().getOrDefault("LLAMA_CPP_MODEL", "qwen3.5-9b");
    private static boolean SEARCH_ENV_WARNING_PRINTED = false;''', flags=re.DOTALL)
    _rewrite(path, r"    // Warn once.*?\n    \}", '''    void reportLlamaCppSearchConfiguration() {
        if (SEARCH_ENV_WARNING_PRINTED || !USE_SEARCH_LLM)
            return;
        System.out.println("[alli] Runtime LLM: llama.cpp endpoint=" + LLAMA_CPP_BASE_URL
                + ", model=" + LLAMA_CPP_MODEL);
        SEARCH_ENV_WARNING_PRINTED = true;
    }''', flags=re.DOTALL)
    _rewrite(path, r"warnIfSearchModelMismatch\(\);", "reportLlamaCppSearchConfiguration();")
    _rewrite(path, r"&& OLLAMA_HOST != null && !OLLAMA_HOST\.isEmpty\(\)\n                && EXPECTED_OLLAMA_MODEL\.equals\(OLLAMA_MODEL\);", "&& LLAMA_CPP_BASE_URL != null && !LLAMA_CPP_BASE_URL.isEmpty()\n                && LLAMA_CPP_MODEL != null && !LLAMA_CPP_MODEL.isEmpty();")
    _rewrite(path, r"    // Call Ollama directly for a single cached label; failures are intentionally non-fatal\.\n    SmallMapAdvice callSmallMapAdvisor\(String prompt\) throws Exception \{.*?\n    \}(?=\n\n    // Read the short)", '''    // The llama.cpp advisor only selects a cached label; failures are non-fatal.
    SmallMapAdvice callSmallMapAdvisor(String prompt) throws Exception {
        String response = LlamaCppChatCompletion.complete(
                LLAMA_CPP_MODEL, prompt, SMALL_MAP_ADVISOR_CONNECT_MS, SMALL_MAP_ADVISOR_READ_MS);
        return parseSmallMapAdvice(response);
    }''', flags=re.DOTALL)
