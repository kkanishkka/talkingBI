// src/components/FileUpload.jsx
export default function FileUpload({ file, onFileSelect }) {
  const handleChange = (e) => {
    const selected = e.target.files?.[0];
    if (selected) onFileSelect(selected);
  };

  return (
    <label className="file-upload">
      <input
        type="file"
        accept=".csv"
        onChange={handleChange}
      />
      <span className="file-upload-icon">⬆</span>
      <span className="file-upload-text">
        <span className="file-upload-title">
          {file ? file.name : "Choose CSV file"}
        </span>
        <span className="file-upload-sub">
          {file
            ? `${(file.size / 1024).toFixed(1)} KB · ready`
            : "click or drag-and-drop"}
        </span>
      </span>
    </label>
  );
}