export function manuscriptFile(title: string, resultVersion: string, body: string) {
  if (!resultVersion.trim() || !body.trim()) throw new Error("缺少已保存的稿件版本或正文");
  const safeName = (value: string, length: number) => Array.from(value.normalize("NFC")
    .replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069<>:"/\\|?*]/g, "_")
    .replace(/^\.+|[.\s]+$/g, "").trim()).slice(0, length).join("");
  return { filename: `${safeName(title, 64) || "稿件"}-${safeName(resultVersion, 64)}.md`, body };
}

export function downloadManuscript(title: string, resultVersion: string, body: string) {
  const file = manuscriptFile(title, resultVersion, body);
  const url = URL.createObjectURL(new Blob([file.body], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename;
  try {
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
