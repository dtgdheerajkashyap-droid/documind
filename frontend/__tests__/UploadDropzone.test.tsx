import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { UploadDropzone, validateFiles } from "@/components/documents/UploadDropzone";
import { ApiError } from "@/lib/api";

const pdf = (name = "report.pdf", size = 1024) =>
  new File([new Uint8Array(size)], name, { type: "application/pdf" });

describe("validateFiles", () => {
  it("accepts PDFs and rejects other types, empty and oversized files", () => {
    const big = pdf("big.pdf", 2 * 1024 * 1024);
    const empty = pdf("empty.pdf", 0);
    const txt = new File(["hi"], "notes.txt", { type: "text/plain" });

    const { accepted, rejected } = validateFiles([pdf(), big, empty, txt], 1);

    expect(accepted.map((f) => f.name)).toEqual(["report.pdf"]);
    expect(rejected).toEqual([
      { filename: "big.pdf", reason: "File exceeds the 1 MB limit." },
      { filename: "empty.pdf", reason: "File is empty." },
      { filename: "notes.txt", reason: "Only PDF files are supported." },
    ]);
  });
});

describe("UploadDropzone", () => {
  it("uploads dropped PDFs and lists files rejected by the client", async () => {
    const onUpload = vi.fn().mockResolvedValue({ documents: [], rejected: [] });
    render(<UploadDropzone onUpload={onUpload} maxSizeMb={1} />);

    fireEvent.drop(screen.getByTestId("dropzone"), {
      dataTransfer: { files: [pdf(), new File(["x"], "photo.png", { type: "image/png" })] },
    });

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect(onUpload.mock.calls[0][0].map((f: File) => f.name)).toEqual(["report.pdf"]);
    expect(await screen.findByText(/Only PDF files are supported/)).toBeInTheDocument();
  });

  it("does not call the API when every file is invalid", async () => {
    const onUpload = vi.fn();
    render(<UploadDropzone onUpload={onUpload} />);

    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [new File(["x"], "data.csv", { type: "text/csv" })] },
    });

    expect(await screen.findByText(/data.csv/)).toBeInTheDocument();
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("shows server-side rejection reasons", async () => {
    const onUpload = vi
      .fn()
      .mockRejectedValue(
        new ApiError("No valid PDF files were uploaded.", 400, "invalid_upload", [
          { filename: "report.pdf", reason: "File content is not a valid PDF." },
        ]),
      );
    render(<UploadDropzone onUpload={onUpload} />);

    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [pdf()] } });

    expect(await screen.findByText(/File content is not a valid PDF/)).toBeInTheDocument();
  });
});
