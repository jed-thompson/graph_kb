/**
 * Strips common AI-generated text artifacts and normalises whitespace
 * for display in the UI.
 */
export function cleanAIText(text: string): string {
  if (!text) return '';

  return text
    // Remove <think>...</think> blocks (extended reasoning traces)
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    // Remove other common XML-style artefact tags
    .replace(/<\/?(?:thinking|reflection|reasoning|scratchpad)>[\s\S]*?<\/(?:thinking|reflection|reasoning|scratchpad)>/gi, '')
    // Collapse runs of blank lines down to a single blank line
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
