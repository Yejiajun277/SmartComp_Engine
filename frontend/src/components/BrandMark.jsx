export default function BrandMark({ compact = false }) {
  return (
    <div className={`brand-mark${compact ? ' brand-mark-compact' : ''}`} aria-label="SmartComp Engine">
      <span className="brand-glyph" aria-hidden="true">
        <span className="brand-glyph-layer brand-glyph-layer-back" />
        <span className="brand-glyph-layer brand-glyph-layer-mid" />
        <span className="brand-glyph-layer brand-glyph-layer-front" />
      </span>
      {!compact && (
        <span className="brand-copy">
          <strong>SmartComp</strong>
          <small>STRATEGY ENGINE</small>
        </span>
      )}
    </div>
  );
}
