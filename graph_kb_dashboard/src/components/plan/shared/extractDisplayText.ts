/**
 * Extract human-readable text from a value that may be:
 * - A plain string
 * - A JSON-encoded string (e.g. '{"text": "..."}')
 * - An object with a display field (text, insight, content, description)
 * - A fallback to String()
 */
export function extractDisplayText(item: unknown): string {
    if (typeof item === 'string') {
        // Backend may send JSON-encoded objects as strings
        try {
            const parsed = JSON.parse(item);
            if (typeof parsed === 'object' && parsed !== null) {
                const obj = parsed as Record<string, unknown>;
                return String(obj.text ?? obj.insight ?? obj.content ?? obj.description ?? item);
            }
            return item;
        } catch {
            return item;
        }
    }
    if (typeof item === 'object' && item !== null) {
        const obj = item as Record<string, unknown>;
        return String(obj.text ?? obj.insight ?? obj.content ?? obj.description ?? JSON.stringify(item));
    }
    return String(item);
}
