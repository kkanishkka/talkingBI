// src/components/FileUpload.jsx
import { useState, useRef } from "react";

const ACCEPTED = ".csv,.xlsx,.xls";

export default function FileUpload({ file, onFileChange }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFileChange(dropped);
  };

  const handleChange = (e) => {
    const picked = e.target.files?.[0];
    if (picked) onFileChange(picked);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    onFileChange(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  if (file) {
    return (
      <div className="file-selected">
        <span>checkmark</span>
        <span className="file-name">{file.name}</span>
        <span style={{ color: "#545c70", fontSize: 12 }}>
          {(file.size / 1024).toFixed(1)} KB
        </span>
        <button className="file-clear" onClick={handleClear} title="Remove file">
          x
        </button>
      </div>
    );
  }

  return (
    <div
      className={`file-upload-zone${dragging ? " drag-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        onChange={handleChange}
        style={{ display: "none" }}
      />
      <div className="upload-icon">folder icon</div>
      <p className="upload-hint">
        <strong>Click to upload</strong> or drag and drop
      </p>
      <p className="upload-hint" style={{ marginTop: 4, fontSize: 12 }}>
        CSV, XLSX, XLS - any schema supported
      </p>
    </div>
  );
}