// src/components/PromptBar.jsx
const EXAMPLES = [
  "Which job category has the highest subscription rate?",
  "Show revenue trend over time",
  "Compare conversion rate by marital status",
  "What is the average balance by job?",
];

export default function PromptBar({ prompt, onPromptChange, onGenerate, disabled }) {
  const placeholder = EXAMPLES[Math.floor(Date.now()/12000) % EXAMPLES.length];

  const handleKey = (e) => {
    if (e.key==="Enter" && !e.shiftKey && !disabled) {
      e.preventDefault(); onGenerate();
    }
  };

  return (
    <div className="prompt-bar">
      <textarea
        className="prompt-input"
        rows={2}
        value={prompt}
        onChange={e=>onPromptChange(e.target.value)}
        onKeyDown={handleKey}
        placeholder={`e.g. "${placeholder}"`}
      />
      <button className="btn-generate" onClick={onGenerate} disabled={disabled}>
        Generate
      </button>
    </div>
  );
}