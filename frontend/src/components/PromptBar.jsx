// src/components/PromptBar.jsx
// Natural-language prompt input + generate button.

const PLACEHOLDER_EXAMPLES = [
  "Give me a complete overview dashboard",
  "Show distribution and trends",
  "Compare categories and highlight outliers",
  "Summarize key metrics and segments",
];

export default function PromptBar({ prompt, onPromptChange, onGenerate, disabled }) {
  // pick a stable placeholder based on current second
  const placeholder =
    PLACEHOLDER_EXAMPLES[Math.floor(Date.now() / 10000) % PLACEHOLDER_EXAMPLES.length];

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !disabled) {
      e.preventDefault();
      onGenerate();
    }
  };

  return (
    <div className="prompt-bar">
      <textarea
        className="prompt-input"
        rows={2}
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={`e.g. "${placeholder}"`}
      />
      <button
        className="btn-generate"
        onClick={onGenerate}
        disabled={disabled}
      >
        Generate
      </button>
    </div>
  );
}