# Invoice & Document Extractor Suite 📄🤖

A comprehensive suite of Streamlit web applications for extracting structured data from invoices and general documents (PDFs and images) using **LangChain**, **Ollama**, **LangGraph**, and **Docling**.

---

## 📋 Overview

This repository provides a collection of interactive applications designed to demonstrate different architectures for document processing. Whether you want a simple linear extraction workflow, a self-correcting agent that validates its own output, or a schema-configurable extractor that lets you define custom fields on-the-fly, you will find a suitable tool in this suite.

All applications run locally using **Ollama** for privacy and offline capability, supporting both multimodal vision models and text-based parsing.

---

## 🚀 Applications in the Suite

| Application File | Purpose & Focus | LLM Input Type | Key Tech | Unique Features |
| :--- | :--- | :--- | :--- | :--- |
| **`invoice_extractor.py`** *(Main)* | **Self-Correcting Invoice Extractor** | Multimodal (Vision) | LangGraph, ChatOllama | **Self-correction (retries)** when critical fields (Total, Vendor, Date, Inv #) are missing; metrics cards; local extraction history (`history.json`). |
| **`extractor_app.py`** | **General Document Extractor** | Text or Multimodal | Docling, ChatOllama | **Dynamic schema editor** (edit & save fields to `field_schema.json`); supports Docling markdown rendering or Multimodal vision; **CSV export**. |
| **`general_app_v2.py`** | **LangGraph General Extractor** | Text or Multimodal | LangGraph, Docling, ChatOllama | Refactored LangGraph implementation of the schema-configurable extractor (`extractor_app.py`). |
| **`docling_app.py`** | **Docling/Multimodal Invoice Extractor** | Text or Multimodal | LangGraph, Docling, ChatOllama | LangGraph-based invoice extractor comparing text-based parsing via Docling vs. vision-based parsing. |
| **`app.py`** | **Basic Invoice Extractor** | Text (PyPDF) or Multimodal | LangGraph, PyPDF, ChatOllama | Basic linear LangGraph pipeline (load -> extract) using `PyPDF` for text parsing. |

---

## 🛠️ Prerequisites

Before running any application, ensure you have the following installed on your system:

### 1. Python 3.12 or later
Check your version with `python --version`.

### 2. Ollama & LLM Models
Download and install Ollama from [ollama.com](https://ollama.com).

Start the Ollama service (`ollama serve`) and pull the models used by the applications:
```bash
# Pull a multimodal vision model (used by invoice_extractor.py & multimodal modes)
ollama pull llava
# or other vision models like
ollama pull qwen3-vl:2b
ollama pull gemma3:4b

# Pull a text-only model (used by Docling / text modes)
ollama pull ministral-3:3b
# or
ollama pull llama3.2
```

### 3. Poppler (System Dependency)
The `pdf2image` library requires **Poppler** to rasterize PDF pages into images for the vision models.
* **Windows**:
  1. Download the latest binary zip from [github.com/oschwartz10612/poppler-windows/releases](https://github.com/oschwartz10612/poppler-windows/releases).
  2. Extract the folder (e.g., to `C:\Program Files\poppler`).
  3. Add the `bin` folder (e.g., `C:\Program Files\poppler\bin`) to your system's environment variable **PATH**.
  4. Restart your terminal/IDE.
* **macOS**:
  ```bash
  brew install poppler
  ```
* **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt-get update
  sudo apt-get install -y poppler-utils
  ```

---

## 📦 Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/Invoice_Extractor.git
   cd Invoice_Extractor
   ```

2. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔧 Configuration

### Environment Variables
Copy `.env.example` to `.env` in the root of the project:
```bash
cp .env.example .env
```

Edit the `.env` file to configure your local Ollama connection and defaults:
```ini
# Ollama server URL (default: http://localhost:11434)
OLLAMA_BASE_URL=http://localhost:11434

# Default model to use (default: llava or ministral-3:3b depending on app)
DEFAULT_MODEL=llava
```

---

## 🎯 Running the Applications

Start any app using `streamlit run <filename>`.

### 1. Self-Correcting Invoice Extractor (Main App)
Features UI cards, validation checking, local history (`history.json`), and self-correction cycles.
```bash
streamlit run invoice_extractor.py
```

### 2. General Document Extractor (Customizable Schema)
Allows you to define what fields to extract inside the UI and export results to CSV.
```bash
streamlit run extractor_app.py
```

### 3. LangGraph General Extractor
Same custom schema flexibility, powered by a LangGraph node-based pipeline.
```bash
streamlit run general_app_v2.py
```

### 4. Docling/Multimodal Invoice Extractor
Uses LangGraph to compare Docling markdown extraction vs. Multimodal vision models.
```bash
streamlit run docling_app.py
```

---

## 📂 Project Structure

```
Invoice_Extractor/
├── .streamlit/
│   └── config.toml      # Custom Slate Dark theme settings for Streamlit
├── example_docs/        # Sample PDFs, images, and statements for testing
│   ├── Downloadable-PDF-Invoices-Add-On-Samples.pdf
│   ├── Simple-Invoice-Template.png
│   ├── Simple-Invoice-Template.webp
│   ├── Simple-Invoice-Template-2x.jpeg
│   ├── Bank-of-America-Statement-BankStatements-net.pdf
│   ├── chase-bank-statement-template-1-1.pdf
│   ├── hourly_invoice_template.png
│   ├── invoice-0-4.pdf
│   ├── invoice-1-3.pdf
│   ├── invoice-2-1.pdf
│   ├── invoice-3-0.pdf
│   ├── invoice-7-0.pdf
│   ├── novelty-bank-statement.webp
│   └── wordpress-pdf-invoice-plugin-sample.pdf
├── .env                # Configured environment variables (Ollama URL, default model)
├── .env.example        # Example environment template
├── .gitignore          # Git ignore patterns
├── AGENTS.md           # LLM agent instructions & guidelines
├── LICENSE             # MIT License
├── app.py              # Basic LangGraph invoice extractor using PyPDF
├── docling_app.py      # LangGraph invoice extractor supporting Docling / Multimodal
├── extractor_app.py    # General Document Extractor with dynamic schema and CSV export
├── field_schema.json   # Schema definitions saved by the general extractors
├── general_app_v2.py   # LangGraph version of the schema-configurable extractor
├── invoice_extractor.py # Main self-correcting invoice extractor with history & metrics
├── requirements.txt    # Required python dependencies (includes streamlit, docling, langgraph, etc.)
└── README.md           # This documentation
```

---

## 🔍 Technical Details & Modes

### 1. Multimodal (Vision) Mode
In this mode, the document (image or PDF) is converted page-by-page (using `pdf2image`) to images. The images are encoded in base64 format and sent directly to Ollama vision-capable models (like `llava` or `qwen3-vl:2b`). This is best for complex, highly-visual invoice templates, bank statements, or tables.

```mermaid
graph TD
    A[Upload PDF/Image] --> B{Is PDF?}
    B -- Yes --> C[Convert first or all pages to PNG via pdf2image]
    B -- No --> D[Use image directly]
    C --> E[Encode image to Base64]
    D --> E
    E --> F[Send Base64 image + prompt to Vision Model]
    F --> G[Extract structured JSON]
```

### 2. Docling + Text LLM Mode
In this mode, the application uses IBM's **Docling** library to parse files (PDFs, DOCX, Images, etc.) and extract their structured content as Markdown. This markdown text is then sent to a standard text LLM (like `ministral-3:3b` or `llama3.2`). This is ideal for text-dense documents, contracts, or when running lighter LLM models that lack vision capabilities.

```mermaid
graph TD
    A[Upload Document] --> B[Docling Converter parses document]
    B --> C[Export to Markdown text]
    C --> D[Send Markdown + Prompt to Text Model]
    D --> E[Extract structured JSON]
```

---

## 🐛 Troubleshooting

### 1. `pdf2image.exceptions.PDFInfoNotInstalledError` / Poppler not found
This happens when `poppler` is missing or not configured in your system's PATH.
* Refer to the **Prerequisites -> Poppler** instructions above.
* Ensure you restarted your IDE or terminal session after updating your environment variables.

### 2. Ollama Connection Error (`ConnectionRefusedError`)
* Make sure the Ollama application is running (`ollama serve`).
* Double-check your `.env` file matches the port where Ollama is listening (typically `http://localhost:11434`).

### 3. Model Not Found
If you see an error indicating that the model cannot be found:
* Verify the model has been downloaded using `ollama list`.
* If it's missing, download it via command line: e.g., `ollama pull llava` or `ollama pull ministral-3:3b`.

### 4. Custom Streamlit Port
If port `8501` is already in use, you can launch Streamlit on a different port:
```bash
streamlit run invoice_extractor.py --server.port 8502
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
