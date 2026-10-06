package rts;

import java.util.Random;

/** Opt-in deterministic randomness for EAGLE-owned MicroRTS matches. */
public final class RandomSource {
    public static final String SEED_PROPERTY = "eagle.match.seed";

    private RandomSource() {
    }

    public static Random create(String namespace) {
        String configured = System.getProperty(SEED_PROPERTY);
        if (configured == null || configured.trim().isEmpty()) {
            return new Random();
        }
        try {
            long seed = Long.parseLong(configured.trim());
            return new Random(mix(seed, namespace == null ? "" : namespace));
        } catch (NumberFormatException ignored) {
            return new Random();
        }
    }

    private static long mix(long seed, String namespace) {
        long value = seed ^ (long) namespace.hashCode() * 0x9E3779B97F4A7C15L;
        value = (value ^ (value >>> 30)) * 0xBF58476D1CE4E5B9L;
        value = (value ^ (value >>> 27)) * 0x94D049BB133111EBL;
        return value ^ (value >>> 31);
    }
}
