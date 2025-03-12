from flask import Flask, render_template, send_file, redirect, url_for, request
import requests
import sqlite3
import xml.etree.ElementTree as ET
from fpdf import FPDF
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
scheduler = BackgroundScheduler()

# Function to extract sitemap URLs from a given XML file
def get_sitemap_urls(sitemap_url):
    response = requests.get(sitemap_url)
    if response.status_code != 200:
        print(f"Failed to fetch {sitemap_url}")
        return []
    
    root = ET.fromstring(response.content)
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    return [elem.text for elem in root.findall('.//ns:loc', namespaces)]

# Function to extract and order company URLs from sitemap files
def get_company_urls_ordered(sitemap_urls):
    ordered_sitemaps = sorted(
        [url for url in sitemap_urls if "companies-sitemap" in url],
        key=lambda x: int(x.split("-sitemap")[-1].split(".xml")[0])
    )

    company_urls = []
    for sitemap_url in ordered_sitemaps:
        print(f"Fetching: {sitemap_url}")
        company_urls.extend(get_sitemap_urls(sitemap_url))  

    return [url for url in company_urls if "/bedrijf/" in url]

# Initialize the database and add necessary columns
def setup_database():
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    
    # Create companies table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            scraped_at TEXT
        )
    """)

    # Create last_checked table to store the last fetch timestamp
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS last_checked (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            new_count INTEGER
        )
    """)

    conn.commit()
    conn.close()

# Save company URLs to the database and store the timestamp
def save_to_database(urls):
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()

    new_records = []
    scraped_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for url in urls:
        try:
            cursor.execute("INSERT INTO companies (url, scraped_at) VALUES (?, ?)", (url, scraped_at))
            new_records.append(url)
        except sqlite3.IntegrityError:
            pass  # Ignore duplicates
    
    cursor.execute("INSERT INTO last_checked (timestamp, new_count) VALUES (?, ?)", (scraped_at, len(new_records)))
    
    conn.commit()
    conn.close()
    
    return new_records

# Fetch all stored companies, ordered by newest first
def fetch_companies():
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, url FROM companies ORDER BY id DESC")  # Newest first
    companies = cursor.fetchall()
    conn.close()
    return companies

# Get the last checked timestamp
def get_last_checked():
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, new_count FROM last_checked ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result if result else ("Never", 0)

# Generate a PDF report of the scraped companies
def generate_pdf():
    companies = fetch_companies()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, "Scraped Companies", ln=True, align='C')
    
    for company in companies:
        pdf.cell(200, 10, company[1], ln=True)
    
    pdf.output("companies.pdf")
    return "companies.pdf"

# Flask Route: Home Page
@app.route('/')
def index():
    companies = fetch_companies()
    total_companies = len(companies)
    last_checked, new_companies = get_last_checked()
    return render_template("index.html", total_companies=total_companies, last_checked=last_checked, new_companies=new_companies)

# Flask Route: Show Companies
@app.route('/companies')
def companies():
    companies = fetch_companies()
    return render_template("companies.html", companies=companies)

# Flask Route: Download PDF
@app.route('/download')
def download():
    pdf_file = generate_pdf()
    return send_file(pdf_file, as_attachment=True)

# Flask Route: Manually Fetch New Companies
@app.route('/fetch_new')
def fetch_new():
    return manual_fetch_new()

# Manually fetch new companies in ordered sequence
def manual_fetch_new():
    sitemap_index_url = "https://informatiegidsen-nederland.nl/sitemap_index.xml"
    all_sitemap_urls = get_sitemap_urls(sitemap_index_url)
    company_urls = get_company_urls_ordered(all_sitemap_urls)
    new_records = save_to_database(company_urls)

    if request and request.method == "GET":
        return render_template("new_records.html", new_records=new_records, count=len(new_records))
    
    print(f"Manual Fetch: {len(new_records)} new records added.")

# Flask Route: Show Recently Added Companies
@app.route('/new_records')
def new_records():
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, url FROM companies ORDER BY id DESC LIMIT 10")
    new_records = cursor.fetchall()
    conn.close()
    return render_template("new_records.html", new_records=new_records)

# Automatically fetch new companies every hour
def auto_fetch():
    with app.app_context():
        print("Auto fetching new companies...")
        sitemap_index_url = "https://informatiegidsen-nederland.nl/sitemap_index.xml"
        all_sitemap_urls = get_sitemap_urls(sitemap_index_url)
        company_urls = get_company_urls_ordered(all_sitemap_urls)
        new_records = save_to_database(company_urls)
        
        print(f"Auto Fetch: {len(new_records)} new companies added.")

# Main Execution
if __name__ == "__main__":
    setup_database()
    sitemap_index_url = "https://informatiegidsen-nederland.nl/sitemap_index.xml"
    all_sitemap_urls = get_sitemap_urls(sitemap_index_url)
    company_urls = get_company_urls_ordered(all_sitemap_urls)
    save_to_database(company_urls)
    print(f"Scraped {len(company_urls)} company URLs and stored in database.")

    scheduler.add_job(auto_fetch, "interval", hours=1)
    scheduler.start()
    
    app.run(debug=True)
