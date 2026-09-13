import { useSourceDocuments } from "../api/hooks";

/**
 * Side drawer for a clicked source citation chip (plan §5: "source
 * citations as clickable chips opening a side drawer"). No document
 * viewer/renderer exists yet to literally scroll a PDF to a page, so this
 * shows the actual cited block's own content instead -- the same
 * information a citation exists to let a reviewer verify, just without a
 * rendered-PDF backdrop around it.
 */
export default function CitationDrawer({
  dealId,
  blockId,
  onClose,
}: {
  dealId: string;
  blockId: string | null;
  onClose: () => void;
}) {
  const documents = useSourceDocuments(dealId);

  if (!blockId) return null;

  const block = documents.data?.flatMap((d) => d.blocks).find((b) => b.id === blockId);
  const doc = documents.data?.find((d) => d.blocks.some((b) => b.id === blockId));

  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-900/20" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-800">Source citation</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            ✕
          </button>
        </div>

        {documents.isLoading && <p className="mt-3 text-sm text-slate-500">Loading…</p>}

        {!documents.isLoading && !block && (
          <p className="mt-3 text-sm text-slate-500">
            Couldn&rsquo;t find block <code>{blockId}</code> -- it may be from manual reviewer input rather than a
            source document.
          </p>
        )}

        {block && doc && (
          <div className="mt-3 flex flex-col gap-2 text-sm">
            <p className="text-xs text-slate-500">
              {doc.filename} · page {block.page} · {block.block_type}
            </p>
            {block.block_type === "table" ? (
              <table className="w-full border-collapse text-xs">
                <tbody>
                  {(block.content as string[][]).map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j} className="border border-slate-200 px-2 py-1">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-700">
                {block.content as string}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}
