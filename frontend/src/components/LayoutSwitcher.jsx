// src/components/LayoutSwitcher.jsx
export default function LayoutSwitcher({ layouts = [], active, onChange }) {
  if (layouts.length < 2) return null;
  return (
    <div className="layout-switcher">
      {layouts.map((layout, i) => (
        <button
          key={layout.layout_id || i}
          className={`layout-btn${i === active ? " active" : ""}`}
          onClick={() => onChange(i)}
          title={layout.description || layout.layout_name}
        >
          {layout.layout_name}
        </button>
      ))}
    </div>
  );
}