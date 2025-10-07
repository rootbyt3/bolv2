#!/usr/bin/env python3
"""
PDF Bill of Lading Address Replacer - Production v3.0
Professional tabbed interface for warehouse users
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import fitz  # PyMuPDF
from pathlib import Path
from multiprocessing import Pool, cpu_count, freeze_support
import sys
import logging
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Sequence
import traceback
import shutil
import json
import re


class AddressTemplate:
    """Manages address templates"""
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = Path(config_file)
        self.templates = {}
        self.recent_addresses = []
        self.load_config()
        
    def load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.templates = data.get('templates', {})
                    self.recent_addresses = data.get('recent_addresses', [])
            except Exception:
                pass
                
    def save_config(self):
        try:
            data = {
                'templates': self.templates,
                'recent_addresses': self.recent_addresses
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Config save failed: {e}")
            
    def add_template(self, name: str, old_addr: Dict, new_addr: Dict):
        self.templates[name] = {'old': old_addr, 'new': new_addr}
        self.save_config()
        
    def get_template(self, name: str) -> Optional[Dict]:
        return self.templates.get(name)
        
    def delete_template(self, name: str):
        if name in self.templates:
            del self.templates[name]
            self.save_config()
            
    def add_recent_address(self, address: Dict):
        self.recent_addresses = [a for a in self.recent_addresses 
                                if a.get('address') != address.get('address')]
        self.recent_addresses.insert(0, address)
        self.recent_addresses = self.recent_addresses[:10]
        self.save_config()


class PDFAddressReplacerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("BOL Address Replacer v3.0")
        self.root.geometry("900x600")
        self.root.minsize(850, 550)
        
        self.template_mgr = AddressTemplate()
        
        # Variables
        self.pdf_folder = tk.StringVar()
        self.old_name = tk.StringVar()
        self.old_address = tk.StringVar()
        self.old_city = tk.StringVar()
        self.new_name = tk.StringVar()
        self.new_address = tk.StringVar()
        self.new_city = tk.StringVar()
        self.create_backup = tk.BooleanVar(value=True)
        self.overwrite_original = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)
        self.use_multiprocessing = tk.BooleanVar(value=True)
        self.selected_template = tk.StringVar(value="-- Select Template --")
        
        # State
        self.processing = False
        self.pdf_files: List[Path] = []
        self.last_backup_dir = None
        
        self.setup_logging()
        self.create_widgets()
        self.center_window()
        
        if not Path("config.json").exists():
            self.root.after(500, self.show_welcome)
        
    def setup_logging(self):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"bol_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.info("Application started")
        
    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
    def show_welcome(self):
        messagebox.showinfo(
            "Welcome",
            "First time setup:\n\n"
            "1. Select your PDF folder\n"
            "2. Click 'Auto-Extract' to fill current values\n"
            "3. Enter new values\n"
            "4. Click 'Process' (starts in safe preview mode)\n\n"
            "Save common addresses as templates for faster processing!"
        )
        
    def create_widgets(self):
        """Create tabbed interface"""
        # Main container
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create notebook (tabs)
        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Tab 1: Main Processing
        self.main_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.main_tab, text="  Process  ")
        
        # Tab 2: Options & Validation
        self.options_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.options_tab, text="  Options  ")
        
        # Tab 3: Log
        self.log_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.log_tab, text="  Log  ")
        
        self.create_main_tab()
        self.create_options_tab()
        self.create_log_tab()
        
        # Status bar
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)
        
    def create_main_tab(self):
        """Main processing tab - clean and simple"""
        # Templates
        template_frame = ttk.LabelFrame(self.main_tab, text="Quick Templates", padding=5)
        template_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(template_frame, text="Load:").pack(side=tk.LEFT, padx=(0, 5))
        self.template_combo = ttk.Combobox(template_frame, textvariable=self.selected_template, 
                                          state='readonly', width=30)
        self.template_combo.pack(side=tk.LEFT, padx=5)
        self.template_combo.bind('<<ComboboxSelected>>', self.load_template)
        
        ttk.Button(template_frame, text="Save Template", 
                  command=self.save_template).pack(side=tk.LEFT, padx=2)
        ttk.Button(template_frame, text="Manage", 
                  command=self.manage_templates).pack(side=tk.LEFT, padx=2)
        
        self.update_template_list()
        
        # Folder
        folder_frame = ttk.LabelFrame(self.main_tab, text="PDF Folder", padding=5)
        folder_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(folder_frame, text="Browse", 
                  command=self.browse_folder, width=10).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(folder_frame, textvariable=self.pdf_folder, 
                 state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.file_count_label = ttk.Label(folder_frame, text="No folder", foreground="gray")
        self.file_count_label.pack(side=tk.LEFT, padx=5)
        
        # Addresses
        addr_frame = ttk.LabelFrame(self.main_tab, text="Address Fields", padding=5)
        addr_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        addr_frame.columnconfigure(1, weight=1)
        addr_frame.columnconfigure(3, weight=1)
        
        # Headers
        ttk.Label(addr_frame, text="Current Values", font=('Arial', 9, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        ttk.Label(addr_frame, text="New Values", font=('Arial', 9, 'bold')).grid(
            row=0, column=2, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        # Name
        ttk.Label(addr_frame, text="Name:").grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(addr_frame, textvariable=self.old_name).grid(
            row=1, column=1, sticky=(tk.W, tk.E), pady=3, padx=(5, 10))
        ttk.Label(addr_frame, text="Name:").grid(row=1, column=2, sticky=tk.W, pady=3)
        ttk.Entry(addr_frame, textvariable=self.new_name).grid(
            row=1, column=3, sticky=(tk.W, tk.E), pady=3, padx=(5, 0))
        
        # Address
        ttk.Label(addr_frame, text="Address:").grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(addr_frame, textvariable=self.old_address).grid(
            row=2, column=1, sticky=(tk.W, tk.E), pady=3, padx=(5, 10))
        ttk.Label(addr_frame, text="Address:").grid(row=2, column=2, sticky=tk.W, pady=3)
        self.new_addr_entry = ttk.Entry(addr_frame, textvariable=self.new_address)
        self.new_addr_entry.grid(row=2, column=3, sticky=(tk.W, tk.E), pady=3, padx=(5, 0))
        self.new_addr_entry.bind('<Button-3>', self.show_recent_addresses)
        
        # City
        ttk.Label(addr_frame, text="City/State/Zip:").grid(row=3, column=0, sticky=tk.W, pady=3)
        old_city_entry = ttk.Entry(addr_frame, textvariable=self.old_city)
        old_city_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=3, padx=(5, 10))
        old_city_entry.bind('<KeyRelease>', self.preview_spacing)
        
        ttk.Label(addr_frame, text="City/State/Zip:").grid(row=3, column=2, sticky=tk.W, pady=3)
        self.new_city_entry = ttk.Entry(addr_frame, textvariable=self.new_city)
        self.new_city_entry.grid(row=3, column=3, sticky=(tk.W, tk.E), pady=3, padx=(5, 0))
        self.new_city_entry.bind('<KeyRelease>', self.preview_spacing)
        
        # Spacing preview
        self.spacing_preview = ttk.Label(addr_frame, text="", foreground="blue", font=('Courier', 8))
        self.spacing_preview.grid(row=4, column=2, columnspan=2, sticky=tk.W, pady=(2, 0))
        
        # Help tip
        ttk.Label(addr_frame, text="Tip: Right-click Address for recent • Spacing auto-matches original", 
                 foreground="gray", font=('Arial', 8)).grid(row=5, column=0, columnspan=4, sticky=tk.W, pady=(5, 0))
        
        # Action buttons
        btn_frame = ttk.Frame(self.main_tab)
        btn_frame.pack(fill=tk.X, pady=10)
        
        self.extract_btn = ttk.Button(btn_frame, text="Auto-Extract Values", 
                                     command=self.extract_from_pdf)
        self.extract_btn.pack(side=tk.LEFT, padx=2)
        
        self.process_btn = ttk.Button(btn_frame, text="Process All PDFs", 
                                     command=self.process_pdfs)
        self.process_btn.pack(side=tk.LEFT, padx=2)
        
        self.undo_btn = ttk.Button(btn_frame, text="Undo Last", 
                                   command=self.undo_last, state=tk.DISABLED)
        self.undo_btn.pack(side=tk.LEFT, padx=2)
        
        # Progress
        self.progress = ttk.Progressbar(btn_frame, mode='determinate', length=200)
        self.progress.pack(side=tk.RIGHT, padx=5)
        self.progress_label = ttk.Label(btn_frame, text="")
        self.progress_label.pack(side=tk.RIGHT, padx=5)
        
    def create_options_tab(self):
        """Options and validation tab"""
        # Options
        opts_frame = ttk.LabelFrame(self.options_tab, text="Processing Options", padding=10)
        opts_frame.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(opts_frame, text="Create backup before processing", 
                       variable=self.create_backup).pack(anchor=tk.W, pady=3)
        ttk.Checkbutton(opts_frame, text="Overwrite original files (no _updated suffix)", 
                       variable=self.overwrite_original).pack(anchor=tk.W, pady=3)
        ttk.Checkbutton(opts_frame, text="Dry run - PREVIEW only, no changes (recommended first run)", 
                       variable=self.dry_run).pack(anchor=tk.W, pady=3)
        ttk.Checkbutton(opts_frame, text=f"Use multiprocessing ({cpu_count()} cores)", 
                       variable=self.use_multiprocessing).pack(anchor=tk.W, pady=3)
        
        # Warning
        warn_frame = ttk.Frame(opts_frame, relief=tk.SOLID, borderwidth=1)
        warn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(warn_frame, text="PRODUCTION: Always test with dry run first!", 
                 foreground="red", font=('Arial', 9, 'bold'), padding=5).pack()
        
        # Validation
        val_frame = ttk.LabelFrame(self.options_tab, text="Pre-Process Validation", padding=10)
        val_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        ttk.Label(val_frame, text="Scan all PDFs before processing to detect issues:", 
                 wraplength=400).pack(anchor=tk.W, pady=(0, 10))
        
        self.validate_btn = ttk.Button(val_frame, text="Validate All PDFs", 
                                      command=self.validate_all_pdfs)
        self.validate_btn.pack(anchor=tk.W)
        
        # Validation results
        self.val_text = scrolledtext.ScrolledText(val_frame, height=10, wrap=tk.WORD, 
                                                 font=('Courier', 9), state=tk.DISABLED)
        self.val_text.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
    def create_log_tab(self):
        """Log output tab"""
        log_frame = ttk.Frame(self.log_tab)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=('Courier', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        btn_frame = ttk.Frame(self.log_tab)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(btn_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Save Log", command=self.save_log).pack(side=tk.LEFT, padx=5)
        
    def update_template_list(self):
        templates = ["-- Select Template --"] + list(self.template_mgr.templates.keys())
        self.template_combo['values'] = templates
        
    def load_template(self, event=None):
        template_name = self.selected_template.get()
        if template_name == "-- Select Template --":
            return
            
        template = self.template_mgr.get_template(template_name)
        if template:
            old = template['old']
            new = template['new']
            
            self.old_name.set(old.get('name', ''))
            self.old_address.set(old.get('address', ''))
            self.old_city.set(old.get('city', ''))
            
            self.new_name.set(new.get('name', ''))
            self.new_address.set(new.get('address', ''))
            self.new_city.set(new.get('city', ''))
            
            self.log_message(f"Loaded template: {template_name}", "success")
            self.preview_spacing()
            
    def save_template(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Save Template")
        dialog.geometry("400x120")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Template Name:").pack(pady=(20, 5))
        name_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=name_var, width=40)
        entry.pack(pady=5)
        entry.focus()
        
        def save():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid", "Enter a template name")
                return
                
            old_addr = {
                'name': self.old_name.get(),
                'address': self.old_address.get(),
                'city': self.old_city.get()
            }
            new_addr = {
                'name': self.new_name.get(),
                'address': self.new_address.get(),
                'city': self.new_city.get()
            }
            
            self.template_mgr.add_template(name, old_addr, new_addr)
            self.update_template_list()
            self.log_message(f"Template saved: {name}", "success")
            dialog.destroy()
        
        ttk.Button(dialog, text="Save", command=save).pack(pady=10)
        dialog.bind('<Return>', lambda e: save())
        
    def manage_templates(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage Templates")
        dialog.geometry("450x300")
        dialog.transient(self.root)
        
        ttk.Label(dialog, text="Saved Templates", font=('Arial', 11, 'bold')).pack(pady=10)
        
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=('Arial', 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        
        for name in self.template_mgr.templates.keys():
            listbox.insert(tk.END, name)
        
        def delete():
            selection = listbox.curselection()
            if selection:
                name = listbox.get(selection[0])
                if messagebox.askyesno("Delete", f"Delete '{name}'?"):
                    self.template_mgr.delete_template(name)
                    listbox.delete(selection[0])
                    self.update_template_list()
        
        ttk.Button(dialog, text="Delete Selected", command=delete).pack(pady=10)
        
    def show_recent_addresses(self, event):
        if not self.template_mgr.recent_addresses:
            return
            
        menu = tk.Menu(self.root, tearoff=0)
        for addr_data in self.template_mgr.recent_addresses[:5]:
            addr = addr_data.get('address', '')
            menu.add_command(label=addr, command=lambda a=addr: self.new_address.set(a))
        
        menu.post(event.x_root, event.y_root)
        
    def preview_spacing(self, event=None):
        old = self.old_city.get()
        new = self.new_city.get()
        
        if not old or not new or '  ' not in old:
            self.spacing_preview.config(text="")
            return
            
        try:
            old_parts = old.split()
            new_parts = new.split()
            
            if len(old_parts) == len(new_parts) == 3:
                city_start = old.find(old_parts[0])
                city_end = city_start + len(old_parts[0])
                state_start = old.find(old_parts[1], city_end)
                state_end = state_start + len(old_parts[1])
                zip_start = old.find(old_parts[2], state_end)
                
                space1 = state_start - city_end
                space2 = zip_start - state_end
                
                formatted = new_parts[0] + (' ' * space1) + new_parts[1] + (' ' * space2) + new_parts[2]
                self.spacing_preview.config(text=f"Will use: '{formatted}'")
        except:
            self.spacing_preview.config(text="")
    
    def browse_folder(self):
        folder = filedialog.askdirectory(title="Select PDF Folder")
        if folder:
            self.pdf_folder.set(folder)
            self.scan_pdf_files()
            if self.pdf_files and not self.old_address.get():
                self.root.after(500, self.extract_from_pdf)
            
    def scan_pdf_files(self):
        try:
            folder = Path(self.pdf_folder.get())
            if not folder.exists():
                self.file_count_label.config(text="Invalid folder")
                return
                
            self.pdf_files = list(folder.glob('*.pdf'))
            count = len(self.pdf_files)
            
            if count == 0:
                self.file_count_label.config(text="No PDFs")
                self.log_message("No PDF files found", "warning")
            else:
                self.file_count_label.config(text=f"{count} PDFs")
                self.log_message(f"Found {count} PDF files", "success")
                self.status_bar.config(text=f"Ready: {count} PDFs")
                
        except Exception as e:
            self.log_message(f"Error: {str(e)}", "error")
            
    def extract_from_pdf(self):
        if not self.pdf_files:
            messagebox.showwarning("No PDFs", "Select a folder first")
            return
            
        try:
            first_pdf = self.pdf_files[0]
            self.log_message(f"Extracting from: {first_pdf.name}", "info")
            self.status_bar.config(text="Extracting...")
            
            doc = fitz.open(str(first_pdf))
            
            for page in doc:
                ship_from = page.search_for("SHIP FROM")
                if not ship_from:
                    continue
                    
                region = fitz.Rect(0, ship_from[0].y0, page.rect.width / 2, ship_from[0].y0 + 200)
                text_dict = page.get_text("dict", clip=region)
                
                name_val = address_val = city_val = ""
                
                if "blocks" in text_dict:
                    for block in text_dict["blocks"]:
                        if "lines" in block:
                            for line in block["lines"]:
                                if "spans" in line:
                                    line_text = "".join(s.get("text", "") for s in line["spans"])
                                    
                                    if "Name:" in line_text:
                                        name_val = line_text.split("Name:", 1)[1].strip() if "Name:" in line_text else ""
                                    elif "Address:" in line_text:
                                        address_val = line_text.split("Address:", 1)[1].strip() if "Address:" in line_text else ""
                                    elif "City/State/Zip:" in line_text:
                                        city_val = line_text.split("City/State/Zip:", 1)[1].strip() if "City/State/Zip:" in line_text else ""
                
                # Fallback
                for label, var_name in [("Name:", "name"), ("Address:", "address"), ("City/State/Zip:", "city")]:
                    if (var_name == "name" and not name_val) or (var_name == "address" and not address_val) or (var_name == "city" and not city_val):
                        lbl = page.search_for(label)
                        if lbl:
                            rect = lbl[0]
                            val_region = fitz.Rect(rect.x1 + 5, rect.y0 - 2, region.x1, rect.y1 + 2)
                            val = page.get_text("text", clip=val_region).strip()
                            if var_name == "name":
                                name_val = val
                            elif var_name == "address":
                                address_val = val
                            else:
                                city_val = val
                
                name_val = " ".join(name_val.split())
                address_val = " ".join(address_val.split())
                # CRITICAL: Don't collapse spaces in city - preserve original spacing
                city_val = city_val.replace('\n', ' ').strip()
                
                if name_val:
                    self.old_name.set(name_val)
                    self.log_message(f"  Name: {name_val}", "success")
                if address_val:
                    self.old_address.set(address_val)
                    self.log_message(f"  Address: {address_val}", "success")
                if city_val:
                    self.old_city.set(city_val)
                    self.log_message(f"  City: {city_val}", "success")
                
                break
                
            doc.close()
            
            if not (name_val or address_val or city_val):
                messagebox.showinfo("Extraction", "Could not extract. Enter manually.")
            else:
                messagebox.showinfo("Success", "Values extracted! Enter new values.")
                self.status_bar.config(text="Values extracted")
                self.preview_spacing()
                
        except Exception as e:
            messagebox.showerror("Error", f"Extraction failed:\n{str(e)}")
            self.log_message(f"Error: {str(e)}", "error")
            
    def validate_all_pdfs(self):
        if not self.pdf_files:
            messagebox.showwarning("No PDFs", "Select a folder first")
            return
            
        self.val_text.config(state=tk.NORMAL)
        self.val_text.delete('1.0', tk.END)
        
        self.val_text.insert(tk.END, "Validating PDFs...\n\n")
        self.status_bar.config(text="Validating...")
        warnings = []
        
        for i, pdf in enumerate(self.pdf_files, 1):
            self.progress['value'] = i
            self.progress['maximum'] = len(self.pdf_files)
            self.root.update_idletasks()
            
            try:
                doc = fitz.open(str(pdf))
                found = any(page.search_for("SHIP FROM") for page in doc)
                doc.close()
                
                if not found:
                    warnings.append(pdf.name)
                    self.val_text.insert(tk.END, f"[!] {pdf.name}: No SHIP FROM\n")
            except Exception as e:
                warnings.append(pdf.name)
                self.val_text.insert(tk.END, f"[X] {pdf.name}: {str(e)}\n")
        
        self.progress['value'] = 0
        self.val_text.insert(tk.END, f"\nValidation complete: {len(warnings)} issues\n")
        self.val_text.config(state=tk.DISABLED)
        
        if warnings:
            messagebox.showwarning("Validation", f"{len(warnings)} PDFs have issues")
        else:
            messagebox.showinfo("Validation", "All PDFs validated successfully!")
        
        self.status_bar.config(text="Validation complete")
        
    def process_pdfs(self):
        if not self.pdf_folder.get() or not self.pdf_files:
            messagebox.showerror("Error", "Select a PDF folder first")
            return
            
        if not self.old_name.get() and not self.old_address.get() and not self.old_city.get():
            messagebox.showerror("Error", "Enter at least one field to replace")
            return
            
        if self.processing:
            return
            
        mode = "DRY RUN" if self.dry_run.get() else "LIVE"
        fields = [f for f, v in [("Name", self.old_name.get()), ("Address", self.old_address.get()), 
                                 ("City", self.old_city.get())] if v]
        
        msg = f"Process {len(self.pdf_files)} PDFs in {mode}?\n\nFields: {', '.join(fields)}"
        if not messagebox.askyesno("Confirm", msg):
            return
            
        self.processing = True
        self.toggle_ui(False)
        self.notebook.select(2)  # Switch to log tab
        self.root.after(100, self.run_processing)
        
    def run_processing(self):
        try:
            self.log_message("="*60, "info")
            self.log_message(f"PROCESSING {len(self.pdf_files)} FILES", "info")
            self.log_message("="*60, "info")
            
            if self.create_backup.get() and not self.dry_run.get():
                self.create_backups()
                
            replacements = {}
            if self.old_name.get():
                replacements['name'] = (self.old_name.get().strip(), self.new_name.get().strip())
            if self.old_address.get():
                replacements['address'] = (self.old_address.get().strip(), self.new_address.get().strip())
            if self.old_city.get():
                replacements['city'] = (self.old_city.get().strip(), self.new_city.get().strip())
            
            args = [(str(pdf), replacements, self.overwrite_original.get(), self.dry_run.get()) 
                    for pdf in self.pdf_files]
            
            if self.use_multiprocessing.get() and len(self.pdf_files) > 1:
                results = self.process_multi(args)
            else:
                results = self.process_single(args)
                
            if not self.dry_run.get() and self.new_address.get():
                self.template_mgr.add_recent_address({
                    'address': self.new_address.get().strip(),
                    'city': self.new_city.get().strip()
                })
                
            self.show_results(results)
            
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.log_message(f"FATAL: {str(e)}", "error")
        finally:
            self.processing = False
            self.toggle_ui(True)
            self.progress['value'] = 0
            
    def process_multi(self, args):
        results = []
        with Pool(cpu_count()) as pool:
            for i, result in enumerate(pool.imap(process_pdf, args), 1):
                results.append(result)
                self.progress['value'] = i
                self.progress_label.config(text=f"{i}/{len(args)}")
                self.root.update_idletasks()
        return results
        
    def process_single(self, args):
        results = []
        for i, arg in enumerate(args, 1):
            result = process_pdf(arg)
            results.append(result)
            self.progress['value'] = i
            self.progress_label.config(text=f"{i}/{len(args)}")
            self.root.update_idletasks()
        return results
        
    def create_backups(self):
        backup_dir = Path(self.pdf_folder.get()) / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(exist_ok=True)
        
        for pdf in self.pdf_files:
            shutil.copy2(pdf, backup_dir / pdf.name)
            
        self.last_backup_dir = backup_dir
        self.undo_btn.config(state=tk.NORMAL)
        self.log_message(f"Backup: {backup_dir.name}", "success")
        
        # Keep last 5
        folder = Path(self.pdf_folder.get())
        backups = sorted([d for d in folder.iterdir() if d.is_dir() and d.name.startswith('backup_')],
                        key=lambda x: x.stat().st_mtime, reverse=True)
        for old in backups[5:]:
            shutil.rmtree(old)
            
    def undo_last(self):
        if not self.last_backup_dir or not self.last_backup_dir.exists():
            messagebox.showwarning("No Backup", "No backup available")
            return
            
        if messagebox.askyesno("Undo", "Restore from backup?"):
            try:
                for backup in self.last_backup_dir.glob('*.pdf'):
                    shutil.copy2(backup, Path(self.pdf_folder.get()) / backup.name)
                messagebox.showinfo("Undo", "Files restored")
                self.log_message("Undo successful", "success")
            except Exception as e:
                messagebox.showerror("Undo Failed", str(e))
                
    def show_results(self, results):
        success = sum(1 for r in results if r['success'])
        errors = len(results) - success
        total_replacements = sum(r['replacements'] for r in results)
        
        self.log_message("\n" + "="*60, "info")
        self.log_message("COMPLETE", "info")
        self.log_message(f"Success: {success}/{len(results)} | Replacements: {total_replacements}", "info")
        
        for r in results:
            status = "[OK]" if r['success'] else "[ERR]"
            msg = f"{status} {r['filename']}: {r['replacements']}" if r['success'] else f"{status} {r['filename']}: {r['error']}"
            self.log_message(msg, "success" if r['success'] else "error")
        
        self.generate_report(results)
        
        summary = f"Complete!\n\nSuccess: {success}/{len(results)}\nReplacements: {total_replacements}"
        if errors:
            summary += f"\n\nErrors: {errors} (see log)"
            messagebox.showwarning("Complete", summary)
        else:
            messagebox.showinfo("Complete", summary)
            
        self.status_bar.config(text=f"Complete: {success} success, {errors} errors")
        
    def generate_report(self, results):
        try:
            report = Path(self.pdf_folder.get()) / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(report, 'w', encoding='utf-8') as f:
                f.write("BOL ADDRESS UPDATE REPORT\n")
                f.write("="*60 + "\n\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Mode: {'DRY RUN' if self.dry_run.get() else 'LIVE'}\n")
                f.write(f"Total: {len(results)}\n")
                f.write(f"Success: {sum(1 for r in results if r['success'])}\n")
                f.write(f"Errors: {sum(1 for r in results if not r['success'])}\n\n")
                
                for r in results:
                    status = "OK" if r['success'] else "ERROR"
                    f.write(f"[{status}] {r['filename']}\n")
                    if r['success']:
                        f.write(f"  Replacements: {r['replacements']}\n")
                    else:
                        f.write(f"  Error: {r['error']}\n")
            
            self.log_message(f"Report saved: {report.name}", "success")
        except Exception as e:
            self.logger.warning(f"Report failed: {e}")
            
    def log_message(self, msg: str, level: str = "info"):
        colors = {"info": "black", "success": "green", "warning": "orange", "error": "red"}
        
        self.log_text.insert(tk.END, msg + "\n")
        last_line = self.log_text.index("end-1c linestart")
        self.log_text.tag_add(level, last_line, "end-1c")
        self.log_text.tag_config(level, foreground=colors.get(level, "black"))
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        
        safe = msg.replace('[OK]', 'OK').replace('[ERR]', 'ERROR')
        getattr(self.logger, level if level != "success" else "info")(safe)
        
    def clear_log(self):
        self.log_text.delete('1.0', tk.END)
        
    def save_log(self):
        content = self.log_text.get('1.0', tk.END)
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile=f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        if filename:
            Path(filename).write_text(content, encoding='utf-8')
            messagebox.showinfo("Saved", f"Log saved to {Path(filename).name}")
        
    def toggle_ui(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.extract_btn.config(state=state)
        self.validate_btn.config(state=state)
        self.process_btn.config(state=state)


def _normalize_token(token: str) -> str:
    """Normalize token to compare words irrespective of punctuation/case."""
    if not token:
        return ""
    return re.sub(r"[^0-9A-Z]+", "", token.upper())


def _find_word_rects(page: fitz.Page, rect: fitz.Rect, tokens: Sequence[str]) -> List[fitz.Rect]:
    """Return bounding boxes for tokens intersecting rect in their original order."""
    if not tokens:
        return []

    try:
        words = page.get_text("words") or []
    except Exception:
        return []

    rect = fitz.Rect(rect)
    relevant = [w for w in words if rect.intersects(fitz.Rect(w[:4]))]
    if not relevant:
        return []

    relevant.sort(key=lambda w: (round(w[1], 3), w[0]))

    normalized_tokens = [_normalize_token(token) for token in tokens]
    positions: List[fitz.Rect] = []
    token_idx = 0

    for word in relevant:
        if token_idx >= len(normalized_tokens):
            break

        if _normalize_token(word[4]) == normalized_tokens[token_idx]:
            positions.append(fitz.Rect(word[:4]))
            token_idx += 1

    if token_idx != len(normalized_tokens):
        return []

    return positions


def process_pdf(args: Tuple) -> dict:
    """Process single PDF"""
    pdf_path, replacements, overwrite, dry_run = args
    
    result = {
        'success': False,
        'filename': Path(pdf_path).name,
        'replacements': 0,
        'error': None
    }
    
    try:
        doc = fitz.open(pdf_path)
        replacement_count = 0
        
        for page in doc:
            ship_from = page.search_for("SHIP FROM")
            if not ship_from:
                continue
                
            region = fitz.Rect(0, ship_from[0].y0, page.rect.width / 2, ship_from[0].y0 + 200)
            
            for field_name, (old_text, new_text) in replacements.items():
                if not new_text:
                    continue
                
                # CRITICAL: Spacing preservation for city/state/zip
                formatted_new_text = new_text
                if field_name == 'city':
                    # Always try to preserve spacing pattern, even if user typed single spaces
                    old_parts = old_text.split()
                    new_parts = new_text.split()
                    
                    # Standard format: City State Zip (3 parts)
                    if len(old_parts) >= 2 and len(new_parts) >= 2:
                        # Find actual spacing in original
                        if len(old_parts) == 3 and len(new_parts) == 3:
                            # Full City State Zip
                            city_pos = old_text.find(old_parts[0])
                            city_end = city_pos + len(old_parts[0])
                            state_pos = old_text.find(old_parts[1], city_end)
                            state_end = state_pos + len(old_parts[1])
                            zip_pos = old_text.find(old_parts[2], state_end)
                            
                            space1 = state_pos - city_end
                            space2 = zip_pos - state_end
                            
                            # Apply original spacing to new text
                            formatted_new_text = new_parts[0] + (' ' * space1) + new_parts[1] + (' ' * space2) + new_parts[2]
                        elif len(old_parts) == 2 and len(new_parts) == 2:
                            # Just City State or State Zip
                            part1_pos = old_text.find(old_parts[0])
                            part1_end = part1_pos + len(old_parts[0])
                            part2_pos = old_text.find(old_parts[1], part1_end)
                            
                            space_between = part2_pos - part1_end
                            formatted_new_text = new_parts[0] + (' ' * space_between) + new_parts[1]
                
                new_text = formatted_new_text
                
                # Search
                instances = page.search_for(old_text)
                if not instances:
                    instances = page.search_for(" ".join(old_text.split()))
                if not instances and field_name == 'city':
                    words = old_text.split()
                    if words:
                        city_inst = page.search_for(words[0])
                        for inst in city_inst:
                            if region.intersects(inst):
                                instances = [fitz.Rect(inst.x0, inst.y0, region.x1, inst.y1)]
                                break
                
                filtered = [i for i in instances if region.intersects(i)]
                if not filtered:
                    continue
                
                # Get font
                text_dict = page.get_text("dict")
                font = "helv"
                size = 10
                color = (0, 0, 0)
                
                span_origin_y = None
                if text_dict and "blocks" in text_dict:
                    for block in text_dict["blocks"]:
                        if "lines" in block:
                            for line in block["lines"]:
                                if "spans" in line:
                                    for span in line["spans"]:
                                        span_rect = fitz.Rect(span["bbox"])
                                        if any(span_rect.intersects(t) for t in filtered):
                                            font = span.get("font", "helv")
                                            size = span.get("size", 10)
                                            c = span.get("color", 0)
                                            if isinstance(c, (list, tuple)):
                                                color = tuple(c)
                                            origin = span.get("origin")
                                            if isinstance(origin, (list, tuple)) and len(origin) == 2:
                                                span_origin_y = origin[1]
                                            break

                # Replace
                for rect in filtered:
                    replacement_count += 1

                    if not dry_run:
                        # Precise bounds
                        # Keep the erasing rectangle from extending above the original text
                        # to avoid overlapping the black "SHIP FROM" banner.
                        cover = fitz.Rect(rect.x0 - 1, rect.y0, rect.x1 + 1, rect.y1 + 1)
                        page.draw_rect(cover, color=(1, 1, 1), fill=(1, 1, 1))

                        baseline = span_origin_y if span_origin_y is not None else rect.y0 + (rect.height * 0.8)

                        # CRITICAL FIX: For city/state/zip, insert each word separately to preserve spacing
                        if field_name == 'city':
                            old_parts = old_text.split()
                            new_parts = new_text.split()

                            word_rects = _find_word_rects(page, rect, old_parts)

                            if word_rects and len(word_rects) == len(new_parts):
                                for new_part, word_rect in zip(new_parts, word_rects):
                                    word_baseline = (
                                        span_origin_y
                                        if span_origin_y is not None
                                        else word_rect.y0 + (word_rect.height * 0.8)
                                    )
                                    point = fitz.Point(word_rect.x0, word_baseline)
                                    try:
                                        page.insert_text(point, new_part, fontname=font, fontsize=size, color=color)
                                    except Exception:
                                        page.insert_text(point, new_part, fontsize=size, color=(0, 0, 0))
                                continue

                            # Fallback to default behavior if word positions cannot be determined
                            try:
                                page.insert_text(fitz.Point(rect.x0, baseline), new_text,
                                               fontname=font, fontsize=size, color=color)
                            except Exception:
                                page.insert_text(fitz.Point(rect.x0, baseline), new_text,
                                               fontsize=size, color=(0, 0, 0))
                        else:
                            # Normal single-word fields
                            try:
                                page.insert_text(fitz.Point(rect.x0, baseline), new_text,
                                               fontname=font, fontsize=size, color=color)
                            except:
                                page.insert_text(fitz.Point(insert_x, baseline), new_text,
                                               fontsize=size, color=(0, 0, 0))
        
        if not dry_run and replacement_count > 0:
            output = pdf_path if overwrite else pdf_path.replace('.pdf', '_updated.pdf')
            doc.save(output, garbage=4, deflate=True)
            
        doc.close()
        result['success'] = True
        result['replacements'] = replacement_count
        
    except Exception as e:
        result['error'] = str(e)
        
    return result


def main():
    freeze_support()
    root = tk.Tk()
    ttk.Style().theme_use('clam')
    app = PDFAddressReplacerGUI(root)
    
    def on_close():
        if app.processing:
            if messagebox.askokcancel("Quit", "Processing in progress. Quit?"):
                root.destroy()
        else:
            root.destroy()
            
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()