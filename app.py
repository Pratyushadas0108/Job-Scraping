from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import schedule
import time
import threading
from email.mime.text import MIMEText
import smtplib
import os
from dotenv import load_dotenv
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Load environment variables
load_dotenv()

# Global Variables
MAX_JOBS_PER_SOURCE = 50  # Maximum number of jobs to fetch from each source
RETRY_ATTEMPTS = 3        # Number of times to retry failed requests
DEFAULT_LOCATION = "India"  # Default location if none specified

SUPPORTED_JOB_SOURCES = {
    'LinkedIn': 'https://www.linkedin.com',
    'TimesJobs': 'https://www.timesjobs.com'
}
CURRENCY_SYMBOL = '₹'     # Currency symbol to display

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jobs.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    search_history = db.relationship('SearchHistory', backref='user', lazy=True)
    job_alerts = db.relationship('JobAlert', backref='user', lazy=True)
    saved_jobs = db.relationship('SavedJob', backref='user', lazy=True)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class JobAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(200))
    min_salary = db.Column(db.Integer)
    experience = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class SavedJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(200))
    salary = db.Column(db.String(200))
    source = db.Column(db.String(100))
    link = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_notified = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Email Configuration
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', 'sasikadas101@gmail.com')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', 'ybfi axrt whbv imwi')

def send_email(to_email, subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp_server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

# User agents for web scraping
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
]

def get_random_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

def convert_to_inr(salary_str):
    if not salary_str or salary_str.lower() == 'salary not specified':
        return None
    
    try:
        if '$' in salary_str:
            return salary_str.replace('$', CURRENCY_SYMBOL)
        return salary_str
    except:
        return salary_str

def parse_salary(salary_str):
    if not salary_str or salary_str.lower() == 'salary not specified':
        return 0
    try:
        # Extract numeric value from salary string (e.g., "₹50,000 - ₹60,000" -> 55000)
        numbers = [int(s) for s in salary_str.replace('₹', '').replace(',', '').split() if s.isdigit()]
        return sum(numbers) // len(numbers) if numbers else 0
    except:
        return 0

def scrape_linkedin(keyword, location=None):
    try:
        if location is None:
            location = DEFAULT_LOCATION
            
        base_url = f"{SUPPORTED_JOB_SOURCES['LinkedIn']}/jobs/search?keywords={keyword}&location={location}"
        headers = get_random_headers()
        
        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = requests.get(base_url, headers=headers)
                response.raise_for_status()
                break
            except:
                if attempt == RETRY_ATTEMPTS - 1:
                    print(f"Failed to fetch LinkedIn jobs after {RETRY_ATTEMPTS} attempts")
                    return []
                time.sleep(2)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        job_cards = soup.find_all('div', {'class': ['base-card', 'job-search-card']})
        
        for card in job_cards[:MAX_JOBS_PER_SOURCE]:
            try:
                title_elem = card.find(['h3', 'h2'], {'class': ['base-search-card__title', 'job-search-card__title']})
                company_elem = card.find(['h4', 'a'], {'class': ['base-search-card__subtitle', 'job-search-card__subtitle']})
                location_elem = card.find('span', {'class': ['job-search-card__location', 'job-result-card__location']})
                salary_elem = card.find(['span', 'div'], {'class': ['job-search-card__salary-info', 'job-result-card__salary-info']})
                link_elem = card.find('a', {'class': ['base-card__full-link', 'job-search-card__link']})
                
                if title_elem and company_elem:
                    jobs.append({
                        'title': title_elem.get_text(strip=True),
                        'company': company_elem.get_text(strip=True),
                        'location': location_elem.get_text(strip=True) if location_elem else "Location not specified",
                        'salary': convert_to_inr(salary_elem.get_text(strip=True)) if salary_elem else None,
                        'source': 'LinkedIn',
                        'link': link_elem['href'] if link_elem and link_elem.get('href') else None
                    })
            except Exception as e:
                print(f"Error parsing LinkedIn job card: {str(e)}")
                continue
        
        return jobs
    except Exception as e:
        print(f"Error scraping LinkedIn: {str(e)}")
        return []

def scrape_timesjobs_jobs(keyword, location=None):
    try:
        if location is None:
            location = DEFAULT_LOCATION
            
        base_url = f"https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&from=submit&txtKeywords={keyword}&txtLocation={location}&cboWorkExp1=0"
        
        print(f"Attempting to fetch TimesJobs URL: {base_url}")
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={random.choice(USER_AGENTS)}')
        chrome_options.add_argument('--window-size=1920,1080')
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        jobs = []
        for attempt in range(RETRY_ATTEMPTS):
            try:
                driver.get(base_url)
                time.sleep(5)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                
                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                
                with open('timesjobs_response.html', 'w', encoding='utf-8') as f:
                    f.write(page_source)
                
                job_cards = soup.find_all('li', {'class': 'clearfix job-bx wht-shd-bx'})
                
                print(f"Found {len(job_cards)} job cards on TimesJobs")
                
                for index, card in enumerate(job_cards[:MAX_JOBS_PER_SOURCE]):
                    try:
                        title_elem = card.find('a', {'target': '_blank'})
                        company_elem = card.find('h3', {'class': 'joblist-comp-name'})
                        
                        location_elem = None
                        top_jd = card.find('ul', {'class': 'top-jd-dtl clearfix'})
                        if top_jd:
                            location_li = top_jd.find('li')
                            if location_li and location_li.find('span'):
                                location_elem = location_li.find('span')
                        
                        salary_elem = None
                        salary_li = card.find('li', {'class': 'salary'})
                        if salary_li:
                            salary_elem = salary_li.find('span')
                        
                        link_elem = card.find('a', {'target': '_blank'})
                        
                        if title_elem and company_elem:
                            job_data = {
                                'title': title_elem.get_text(strip=True),
                                'company': company_elem.get_text(strip=True).split('\n')[0].strip(),
                                'location': location_elem.get_text(strip=True) if location_elem else location,
                                'salary': convert_to_inr(salary_elem.get_text(strip=True)) if salary_elem else None,
                                'source': 'TimesJobs',
                                'link': link_elem['href'] if link_elem and link_elem.get('href') else None
                            }
                            
                            print(f"Found TimesJobs job: {job_data['title']} at {job_data['company']}")
                            jobs.append(job_data)
                        else:
                            print(f"Skipping job card {index}: Missing title or company")
                    except Exception as e:
                        print(f"Error parsing TimesJobs job card {index}: {str(e)}")
                        with open(f'timesjobs_failed_card_{index}.html', 'w', encoding='utf-8') as f:
                            f.write(str(card))
                        continue
                
                break
            except Exception as e:
                print(f"TimesJobs request failed (attempt {attempt + 1}): {str(e)}")
                if attempt == RETRY_ATTEMPTS - 1:
                    print("All retry attempts failed for TimesJobs")
                    driver.quit()
                    return []
                time.sleep(2)
        
        driver.quit()
        print(f"Successfully scraped {len(jobs)} jobs from TimesJobs")
        return jobs
    except Exception as e:
        print(f"Error in TimesJobs scraper: {str(e)}")
        if 'driver' in locals():
            driver.quit()
        return []

def search_jobs(query, location=None, user_id=None):
    all_jobs = []
    seen_jobs = set()  # Track unique jobs by title and company
    
    # Search LinkedIn
    print("Searching LinkedIn...")
    linkedin_jobs = scrape_linkedin(query, location)
    print(f"Found {len(linkedin_jobs)} jobs from LinkedIn")
    
    for job in linkedin_jobs:
        job_key = (job['title'].lower(), job['company'].lower())
        if job_key not in seen_jobs:
            seen_jobs.add(job_key)
            all_jobs.append(job)
    
    # Search TimesJobs
    print("Searching TimesJobs...")
    timesjobs_jobs = scrape_timesjobs_jobs(query, location)
    print(f"Found {len(timesjobs_jobs)} jobs from TimesJobs")
    
    for job in timesjobs_jobs:
        job_key = (job['title'].lower(), job['company'].lower())
        if job_key not in seen_jobs:
            seen_jobs.add(job_key)
            all_jobs.append(job)
    
    # Check for job alerts and notify user
    if user_id and all_jobs:
        try:
            user = User.query.get(user_id)
            if user and user.email:
                # Check for job alerts and notify user
                alerts = JobAlert.query.filter_by(user_id=user_id).all()
                matching_jobs = []
                
                for job in all_jobs:
                    for alert in alerts:
                        if (alert.keyword.lower() in job['title'].lower() or
                            alert.keyword.lower() in job['company'].lower()):
                            if alert.location and alert.location.lower() not in job['location'].lower():
                                continue
                            if alert.min_salary and job['salary'] and alert.min_salary > parse_salary(job['salary']):
                                continue
                            matching_jobs.append(job)
                
                if matching_jobs:
                    subject = f"New Job Listings for Your Search: {query}"
                    body = f"Hello {user.username},\n\n"
                    body += f"We found {len(matching_jobs)} new job listings matching your alert criteria.\n\n"
                    
                    for job in matching_jobs:
                        body += f"Title: {job['title']}\n"
                        body += f"Company: {job['company']}\n"
                        body += f"Location: {job['location']}\n"
                        if job['salary']:
                            body += f"Salary: {job['salary']}\n"
                        body += f"Source: {job['source']}\n"
                        if job['link']:
                            body += f"Link: {job['link']}\n"
                        body += "\n"
                    
                    body += "Best regards,\nYour Job Search Assistant"
                    
                    send_email(user.email, subject, body)
        except Exception as e:
            print(f"Error processing job alerts: {str(e)}")
    
    if not all_jobs:
        flash("No jobs found. Please try different search terms or location.", "warning")
    else:
        flash(f"Found {len(all_jobs)} jobs matching your search.", "success")
    
    print(f"Total unique jobs found: {len(all_jobs)}")
    return all_jobs

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email, password=password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username, password=password).first()
        
        if user:
            login_user(user)
            return redirect(url_for('dashboard'))
        
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    search_history = SearchHistory.query.filter_by(user_id=current_user.id).order_by(SearchHistory.timestamp.desc()).all()
    job_alerts = JobAlert.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', search_history=search_history, job_alerts=job_alerts)

@app.route('/search', methods=['POST'])
@login_required
def search():
    keyword = request.form['keyword']
    location = request.form['location']
    
    search = SearchHistory(keyword=keyword, location=location, user_id=current_user.id)
    db.session.add(search)
    db.session.commit()
    
    jobs = search_jobs(keyword, location, current_user.id)
    return render_template('results.html', jobs=jobs, keyword=keyword, location=location)

@app.route('/save_job', methods=['POST'])
@login_required
def save_job():
    try:
        job_data = request.json
        if not job_data:
            return jsonify({'success': False, 'message': 'No job data provided'})
        
        # Check if job already exists
        existing_job = SavedJob.query.filter_by(
            title=job_data['title'],
            company=job_data['company'],
            user_id=current_user.id
        ).first()
        
        if existing_job:
            print(f"Job already saved: {job_data['title']} at {job_data['company']}")
            return jsonify({'success': False, 'message': 'Job already saved'})
        
        # Create new saved job
        saved_job = SavedJob(
            title=job_data['title'],
            company=job_data['company'],
            location=job_data.get('location'),
            salary=job_data.get('salary'),
            source=job_data.get('source'),
            link=job_data.get('link'),
            user_id=current_user.id
        )
        
        db.session.add(saved_job)
        db.session.commit()
        
        print(f"Job saved: {job_data['title']} at {job_data['company']} by user {current_user.id}")
        return jsonify({'success': True, 'message': 'Job saved successfully'})
    except Exception as e:
        print(f"Error saving job: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error saving job: {str(e)}'})

@app.route('/send_saved_jobs', methods=['POST'])
@login_required
def send_saved_jobs():
    saved_jobs = SavedJob.query.filter_by(user_id=current_user.id, is_notified=False).all()
    
    if saved_jobs:
        subject = "Your Saved Job Listings"
        body = f"Hello {current_user.username},\n\n"
        body += f"Here are your saved job listings:\n\n"
        
        for job in saved_jobs:
            body += f"Title: {job.title}\n"
            body += f"Company: {job.company}\n"
            body += f"Location: {job.location}\n"
            if job.salary:
                body += f"Salary: {job.salary}\n"
            body += f"Link: {job.link}\n\n"
        
        body += "Best regards,\nYour Job Search Assistant"
        
        if send_email(current_user.email, subject, body):
            for job in saved_jobs:
                job.is_notified = True
            db.session.commit()
            return jsonify({'success': True, 'message': 'Email sent successfully!'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send email'})
    else:
        return jsonify({'success': False, 'message': 'No saved jobs to send'})

@app.route('/saved_jobs')
@login_required
def saved_jobs():
    saved_jobs = SavedJob.query.filter_by(user_id=current_user.id).order_by(SavedJob.timestamp.desc()).all()
    return render_template('saved_jobs.html', saved_jobs=saved_jobs)

@app.route('/create_alert', methods=['POST'])
@login_required
def create_alert():
    keyword = request.form['keyword']
    location = request.form['location']
    min_salary = request.form.get('min_salary')
    experience = request.form.get('experience')
    
    alert = JobAlert(
        keyword=keyword,
        location=location,
        min_salary=min_salary,
        experience=experience,
        user_id=current_user.id
    )
    db.session.add(alert)
    db.session.commit()
    
    flash('Job alert created successfully!')
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/clear_saved_jobs')
@login_required
def clear_saved_jobs():
    SavedJob.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash('All saved jobs have been cleared.', 'success')
    return redirect(url_for('saved_jobs'))

def check_job_alerts():
    with app.app_context():
        alerts = JobAlert.query.all()
        for alert in alerts:
            jobs = search_jobs(alert.keyword, alert.location, alert.user_id)
            if jobs:
                user = User.query.get(alert.user_id)
                email_body = "\n".join([f"{job['title']} at {job['company']} - {job['salary']} ({job['source']})" for job in jobs])
                send_email(user.email, f"New Job Alerts for {alert.keyword}", email_body)

def run_scheduler():
    schedule.every(1).hours.do(check_job_alerts)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    app.run(debug=True)