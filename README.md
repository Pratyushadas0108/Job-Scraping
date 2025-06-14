
Job Scraper Application
A web-based job search platform that aggregates job listings from multiple websites, allows user account management, and delivers personalized job alerts based on user preferences.

1. Description
The Job Scraper Application is designed to simplify and automate the job-hunting process. It collects listings from various job portals and presents them in a centralized interface. Users can create accounts, apply filters to their searches, save search history, and receive notifications when new relevant jobs are posted.

2. Features
User authentication (registration and login system)

Job search across multiple external job listing websites

Custom job filters including location, salary, and experience level

Automatically saved search history for registered users

Ability to create job alerts with custom criteria

Email notifications for new job postings that match user preferences

3. Technologies Used
Python (Flask framework for backend)

HTML, CSS, JavaScript (for frontend UI and interactivity)

SQLite (lightweight database for storing user and job data)

BeautifulSoup and Requests (for web scraping job listings)

SMTP (for sending job alerts via email)

4. Security Notes
Basic authentication with Flask-Login for session handli

In production, password hashing and secure storage practices are necessary

Sensitive information like email credentials should be stored securely using environment variables

5. License
This project is licensed under the MIT License.
