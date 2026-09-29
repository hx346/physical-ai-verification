package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 场景库跨 seed 分析纯逻辑（2026-09-23）：
 * Wilson 区间边界（n=0 不编造 / 全成功封顶 / 小样本更宽）与
 * variant 归并键（键序无关 / seed 剥离 / 参数差异可辨）。
 */
class ScenarioControllerTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static JsonNode json(String s) throws Exception {
        return MAPPER.readTree(s);
    }

    @Test
    void wilsonZeroNReturnsZeroZero() {
        double[] w = ScenarioController.wilson(0, 0);
        assertEquals(0.0, w[0]);
        assertEquals(0.0, w[1]);
    }

    @Test
    void wilsonAllSuccessCappedAtOne() {
        double[] w = ScenarioController.wilson(10, 10);
        assertTrue(w[0] > 0.72, "low=" + w[0]);
        assertEquals(1.0, w[1]);
        assertTrue(w[0] < 1.0);
    }

    @Test
    void wilsonHalfHalfContainsHalf() {
        double[] w = ScenarioController.wilson(5, 10);
        assertTrue(w[0] < 0.5 && w[1] > 0.5);
        assertEquals(w[0], 1.0 - w[1], 1e-9); // p=0.5 区间对称
    }

    @Test
    void wilsonSmallerSampleWiderInterval() {
        double width2 = width(ScenarioController.wilson(1, 2));
        double width100 = width(ScenarioController.wilson(50, 100));
        assertTrue(width2 > width100);
    }

    private static double width(double[] w) {
        return w[1] - w[0];
    }

    @Test
    void variantKeyIgnoresKeyOrderAndSeed() throws Exception {
        String a = ScenarioController.variantKey(json("{\"seed\":42,\"bin\":{\"width\":0.7,\"depth\":0.45},\"place\":{\"x\":1.25}}"));
        String b = ScenarioController.variantKey(json("{\"place\":{\"x\":1.25},\"bin\":{\"depth\":0.45,\"width\":0.7},\"seed\":7}"));
        assertEquals(a, b);
    }

    @Test
    void variantKeyIgnoresNestedKeyOrder() throws Exception {
        String a = ScenarioController.variantKey(json("{\"bin\":{\"width\":0.7,\"spawn\":{\"z\":0.18}}}"));
        String b = ScenarioController.variantKey(json("{\"bin\":{\"spawn\":{\"z\":0.18},\"width\":0.7}}"));
        assertEquals(a, b);
    }

    @Test
    void variantKeyDistinguishesParameters() throws Exception {
        String a = ScenarioController.variantKey(json("{\"seed\":42,\"bin\":{\"width\":0.7}}"));
        String b = ScenarioController.variantKey(json("{\"seed\":42,\"bin\":{\"width\":0.45}}"));
        assertNotEquals(a, b);
    }

    @Test
    void variantKeyNormalizesNumericTypes() throws Exception {
        // 手工注册 int 600 与 echo float 600.0 同值应同键，否则变体计数虚增
        String a = ScenarioController.variantKey(json("{\"bin\":{\"width_mm\":600}}"));
        String b = ScenarioController.variantKey(json("{\"bin\":{\"width_mm\":600.0}}"));
        assertEquals(a, b);
    }

    @Test
    void variantKeyNormalizesExponentNotation() throws Exception {
        String a = ScenarioController.variantKey(json("{\"bin\":{\"width\":0.7}}"));
        String b = ScenarioController.variantKey(json("{\"bin\":{\"width\":7e-1}}"));
        assertEquals(a, b);
    }

    @Test
    void nullSeedBucketsWithoutNpe() {
        // 回归：bySeed 曾是 TreeMap——computeIfAbsent(null) 抛 NPE，单条缺数字
        // seed 的实例（如字符串 seed echo）曾让整个 analysis 端点持续 500
        ScenarioController.FamilyAcc fa = new ScenarioController.FamilyAcc();
        fa.bySeed.computeIfAbsent(null, k -> new ScenarioController.RunAcc()).n = 1;
        fa.bySeed.computeIfAbsent(42L, k -> new ScenarioController.RunAcc()).n = 2;
        assertEquals(2, fa.bySeed.size());
        assertEquals(1, fa.bySeed.get(null).n);
    }

    @Test
    void tagFilterJsonEscapesBackslashAndQuote() throws Exception {
        // 回归：手拼 JSON 曾漏反斜杠转义——tag 以反斜杠结尾产出非法 jsonb → PG 500
        String s = ScenarioController.tagFilterJson("family\\x\"");
        JsonNode arr = json(s);
        assertEquals(1, arr.size());
        assertEquals("family\\x\"", arr.get(0).asText());
    }
}
