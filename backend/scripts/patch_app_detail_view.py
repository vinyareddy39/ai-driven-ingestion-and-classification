with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Tables Section
old_tables_marker = "                                {/* Tables Section */}\n                                {draftTables && draftTables.length > 0 && ("
new_tables_block = """                                {/* Tables Section: Render table only if document really has one */}
                                {(() => {
                                  if (!draftTables || draftTables.length === 0) return null;

                                  const validTables = draftTables.filter((tbl) =>
                                    tbl &&
                                    tbl.headers &&
                                    tbl.headers.length > 0 &&
                                    tbl.rows &&
                                    tbl.rows.some((row) =>
                                      Object.values(row).some((v) => v && String(v).trim().length > 0)
                                    )
                                  );

                                  if (validTables.length === 0) return null;

                                  return (
                                    <div style={{ marginBottom: '20px' }}>
                                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                        <h3 style={{ margin: 0, fontSize: '15px' }}>Structured Tables ({validTables.length})</h3>
                                      </div>
                                      {validTables.map((tbl, tIdx) => {
                                        const isSummaryRow = (row: Record<string, string>) => {
                                          const text = Object.values(row).join(' ').toLowerCase();
                                          return /subtotal|sub-total|total tax|tax\\b|vat\\b|sales tax|grand total|^total\\b|balance due|amount due/i.test(text);
                                        };
                                        const lineItems = tbl.rows.filter((r) => !isSummaryRow(r) && Object.values(r).some((v) => v && String(v).trim().length > 0));
                                        const tableSummaryRows = tbl.rows.filter((r) => isSummaryRow(r));

                                        // Extract summary totals: Subtotal, Tax, Total
                                        const summaryTotals: Array<{ label: string; value: string }> = [];
                                        tableSummaryRows.forEach((row) => {
                                          const keys = Object.keys(row);
                                          const labelKey = keys.find((k) => /desc|item|particular|name|type|label/i.test(k)) || keys[0];
                                          const valKey = keys.find((k) => /amount|total|price|val/i.test(k)) || keys[keys.length - 1];
                                          if (row[labelKey] || row[valKey]) {
                                            summaryTotals.push({ label: row[labelKey] || 'Total', value: row[valKey] || '' });
                                          }
                                        });
                                        tableTotalsGroup.forEach(({ item }) => {
                                          if (!summaryTotals.some((st) => st.label.toLowerCase() === item.label.toLowerCase())) {
                                            summaryTotals.push({ label: item.label || 'Total', value: item.value || '' });
                                          }
                                        });

                                        // Count unsure cells
                                        let unsureCellCount = 0;
                                        lineItems.forEach((row) => {
                                          tbl.headers.forEach((h) => {
                                            const val = row[h];
                                            if (!val || !val.trim() || val === '?' || val === '[unclear]') {
                                              unsureCellCount++;
                                            }
                                          });
                                        });

                                        return (
                                          <div key={tIdx} style={{ marginBottom: '16px', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', background: 'var(--card)' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '6px' }}>
                                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span style={{ fontWeight: 600, fontSize: '13px' }}>
                                                  Table {tIdx + 1} (Page {tbl.page || 1}) · {lineItems.length} line items
                                                </span>
                                                {unsureCellCount > 0 && (
                                                  <span className="pill warn" style={{ fontSize: '11px', padding: '2px 6px' }}>
                                                    ⚠️ {unsureCellCount} unsure cell{unsureCellCount > 1 ? 's' : ''}
                                                  </span>
                                                )}
                                              </div>
                                              <div style={{ display: 'flex', gap: '6px' }}>
                                                <button type="button" className="btn" style={{ fontSize: '11px', padding: '2px 8px' }} onClick={() => addTableColumn(tIdx)}>+ Column</button>
                                                <button type="button" className="btn" style={{ fontSize: '11px', padding: '2px 8px' }} onClick={() => addTableRow(tIdx)}>+ Line Item</button>
                                              </div>
                                            </div>

                                            {/* Arithmetic check status badges */}
                                            {tbl.arithmetic_checks && tbl.arithmetic_checks.length > 0 && (
                                              <div style={{ marginBottom: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                {tbl.arithmetic_checks.map((chk, cIdx) => (
                                                  <div
                                                    key={cIdx}
                                                    style={{
                                                      fontSize: '11px',
                                                      padding: '3px 6px',
                                                      borderRadius: '4px',
                                                      background: chk.status === 'verified' ? '#f0fdf4' : '#fef2f2',
                                                      color: chk.status === 'verified' ? '#166534' : '#991b1b',
                                                      border: `1px solid ${chk.status === 'verified' ? '#bbf7d0' : '#fecaca'}`,
                                                    }}
                                                  >
                                                    <span>{chk.status === 'verified' ? '✓ ' : '⚠️ '}</span>
                                                    <span><strong>{chk.type.toUpperCase()}:</strong> {chk.message}</span>
                                                  </div>
                                                ))}
                                              </div>
                                            )}

                                            {/* Grid Table for Line Items */}
                                            <div style={{ overflowX: 'auto' }}>
                                              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                                                <thead>
                                                  <tr style={{ background: 'var(--card-hover)', borderBottom: '1px solid var(--border)' }}>
                                                    <th style={{ width: '28px', padding: '4px', textAlign: 'center' }}>#</th>
                                                    {tbl.headers.map((h, hIdx) => (
                                                      <th key={hIdx} style={{ padding: '6px', textAlign: 'left' }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                          <input
                                                            type="text"
                                                            value={h}
                                                            onChange={(e) => updateTableHeader(tIdx, hIdx, e.target.value)}
                                                            style={{ fontWeight: 600, padding: '2px 4px', width: '100%', fontSize: '11px' }}
                                                          />
                                                          <button
                                                            type="button"
                                                            onClick={() => removeTableColumn(tIdx, hIdx)}
                                                            title="Delete column"
                                                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted)', fontSize: '11px' }}
                                                          >
                                                            ✕
                                                          </button>
                                                        </div>
                                                      </th>
                                                    ))}
                                                    <th style={{ width: '32px', padding: '4px' }}></th>
                                                  </tr>
                                                </thead>
                                                <tbody>
                                                  {lineItems.map((row, rIdx) => (
                                                    <tr key={rIdx} style={{ borderBottom: '1px solid var(--border)' }}>
                                                      <td style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '11px' }}>{rIdx + 1}</td>
                                                      {tbl.headers.map((h, hIdx) => {
                                                        const cellVal = row[h] || '';
                                                        const isCellUnsure = !cellVal || !cellVal.trim() || cellVal === '?' || cellVal === '[unclear]';
                                                        return (
                                                          <td key={hIdx} style={{ padding: '3px' }}>
                                                            <input
                                                              type="text"
                                                              value={cellVal}
                                                              onChange={(e) => updateTableCell(tIdx, rIdx, h, e.target.value)}
                                                              style={{
                                                                width: '100%',
                                                                padding: '3px 5px',
                                                                fontSize: '12px',
                                                                border: isCellUnsure ? '1px solid #f59e0b' : '1px solid var(--border)',
                                                                background: isCellUnsure ? 'rgba(245, 158, 11, 0.08)' : 'var(--panel)',
                                                              }}
                                                            />
                                                          </td>
                                                        );
                                                      })}
                                                      <td style={{ textAlign: 'center', padding: '3px' }}>
                                                        <button
                                                          type="button"
                                                          onClick={() => removeTableRow(tIdx, rIdx)}
                                                          title="Delete line item"
                                                          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: '12px' }}
                                                        >
                                                          ✕
                                                        </button>
                                                      </td>
                                                    </tr>
                                                  ))}
                                                </tbody>
                                              </table>
                                            </div>

                                            {/* Summary block under table: Subtotal, Tax, Total shown once */}
                                            {summaryTotals.length > 0 && (
                                              <div style={{ marginTop: '14px', display: 'flex', justifyContent: 'flex-end' }}>
                                                <div style={{ minWidth: '240px', maxWidth: '320px', padding: '10px 14px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid var(--border)', borderRadius: '6px' }}>
                                                  <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Summary Totals</div>
                                                  {summaryTotals.map((tot, sIdx) => (
                                                    <div key={sIdx} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '13px', borderTop: sIdx > 0 ? '1px dashed var(--border)' : 'none' }}>
                                                      <span style={{ color: 'var(--muted)', fontWeight: 500 }}>{tot.label}:</span>
                                                      <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>{tot.value}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  );
                                })()}"""

# Find the end of tables section (before datalist id="doc-label-suggestions")
end_marker = '                                <datalist id="doc-label-suggestions">'
start_idx = content.find(old_tables_marker)
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + new_tables_block + "\n\n" + content[end_idx:]
    print("Replaced tables section successfully.")
else:
    print(f"Could not find tables markers: start_idx={start_idx}, end_idx={end_idx}")

# 2. Remove duplicate Attached Table Totals
old_totals_block = """                                {/* 7. Attached Table Totals */}
                                {tableTotalsGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>Attached Table Totals ({tableTotalsGroup.length})</h3>
                                    {tableTotalsGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}"""
if old_totals_block in content:
    content = content.replace(old_totals_block, "                                {/* Attached Table Totals rendered under table summary above */}")
    print("Removed duplicate Attached Table Totals successfully.")
else:
    print("Could not find Attached Table Totals block directly, searching fuzzy...")
    import re
    content = re.sub(
        r'\{\/\* 7\. Attached Table Totals \*\/\}[\s\S]*?\{tableTotalsGroup\.map\([\s\S]*?\)\s*\}\s*<\/div>\s*\)\}',
        '{/* Attached Table Totals rendered under table summary above */}',
        content
    )
    print("Replaced Attached Table Totals with regex.")

with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated frontend/src/App.tsx successfully.")
