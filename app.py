from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import json
from openai import OpenAI
import feedparser
import hashlib
import random
from datetime import datetime
import sqlite3
import psycopg2
from urllib.parse import urlparse
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)
app.secret_key = 'mindcrew_secret_key_2024'

@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ['https://www.upwork.com', 'http://localhost:3000', 'chrome-extension://']:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Chrome-Extension')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

import os

# Configuration
OPENAI_KEY = os.getenv('OPENAI_KEY', 'your-openai-key-here')
OLOSTEP_KEY = os.getenv('OLOSTEP_KEY', 'your-olostep-key-here')
COUNTRIES = ["singapore", "hongkong", "india", "malaysia", "thailand", "philippines", "vietnam", "indonesia"]
GENERIC_KEYWORDS = ["real estate", "habit tracking", "expenses", "calory counter", "fitness", "education", "shopping", "travel", "food delivery", "dating"]

client = OpenAI(api_key=OPENAI_KEY)

class MultiRSSProposalSystem:
    def __init__(self):
        self.init_db()
        self.rss_threads = {}
        
    def get_db_connection(self):
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            # PostgreSQL connection
            return psycopg2.connect(database_url)
        else:
            # SQLite fallback for local development
            return sqlite3.connect('proposals.db')
    
    def init_db(self):
        conn = self.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        # Users table
        if is_postgres:
            # PostgreSQL syntax
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (id SERIAL PRIMARY KEY, email TEXT UNIQUE, password TEXT, active INTEGER DEFAULT 1)''')
        else:
            # SQLite syntax
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (id INTEGER PRIMARY KEY, email TEXT UNIQUE, password TEXT, active INTEGER DEFAULT 1)''')
        
        # Insert hardcoded user if not exists
        if is_postgres:
            c.execute("SELECT COUNT(*) FROM users WHERE email = %s", ('madhuri.thakur@mindcrewtech.com',))
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO users (email, password) VALUES (%s, %s)", 
                         ('madhuri.thakur@mindcrewtech.com', 'mindcrew01'))
        else:
            c.execute("SELECT COUNT(*) FROM users WHERE email = ?", ('madhuri.thakur@mindcrewtech.com',))
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO users (email, password) VALUES (?, ?)", 
                         ('madhuri.thakur@mindcrewtech.com', 'mindcrew01'))
        
        # RSS Feeds table
        if is_postgres:
            c.execute('''CREATE TABLE IF NOT EXISTS rss_feeds
                         (id SERIAL PRIMARY KEY, name TEXT, url TEXT, active INTEGER DEFAULT 1,
                          keyword_prompt TEXT, proposal_prompt TEXT, olostep_prompt TEXT)''')
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS rss_feeds
                         (id INTEGER PRIMARY KEY, name TEXT, url TEXT, active INTEGER DEFAULT 1,
                          keyword_prompt TEXT, proposal_prompt TEXT, olostep_prompt TEXT)''')
        
        # Jobs table with RSS source
        if is_postgres:
            c.execute('''CREATE TABLE IF NOT EXISTS jobs
                         (id TEXT PRIMARY KEY, title TEXT, description TEXT, url TEXT, 
                          client TEXT, budget TEXT, posted_date TEXT, processed INTEGER DEFAULT 0,
                          client_type TEXT, client_name TEXT, client_company TEXT, client_city TEXT, 
                          client_country TEXT, linkedin_url TEXT, email TEXT, phone TEXT, 
                          whatsapp TEXT, enriched INTEGER DEFAULT 0, decision_maker TEXT,
                          skills TEXT, categories TEXT, hourly_rate TEXT, site TEXT, rss_source_id INTEGER)''')
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS jobs
                         (id TEXT PRIMARY KEY, title TEXT, description TEXT, url TEXT, 
                          client TEXT, budget TEXT, posted_date TEXT, processed INTEGER DEFAULT 0,
                          client_type TEXT, client_name TEXT, client_company TEXT, client_city TEXT, 
                          client_country TEXT, linkedin_url TEXT, email TEXT, phone TEXT, 
                          whatsapp TEXT, enriched INTEGER DEFAULT 0, decision_maker TEXT,
                          skills TEXT, categories TEXT, hourly_rate TEXT, site TEXT, rss_source_id INTEGER)''')
        
        if is_postgres:
            c.execute('''CREATE TABLE IF NOT EXISTS proposals
                         (id SERIAL PRIMARY KEY, job_id TEXT UNIQUE, proposal TEXT, 
                          examples TEXT, created_at TEXT, debug_log TEXT, enrichment_author TEXT)''')
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS proposals
                         (id INTEGER PRIMARY KEY, job_id TEXT UNIQUE, proposal TEXT, 
                          examples TEXT, created_at TEXT, debug_log TEXT, enrichment_author TEXT)''')
        
        # Team profiles table
        if is_postgres:
            c.execute('''CREATE TABLE IF NOT EXISTS team_profiles
                         (id SERIAL PRIMARY KEY, name TEXT, title TEXT, skills TEXT, 
                          description TEXT, profile_url TEXT, hourly_rate TEXT, 
                          experience_years INTEGER, specialization TEXT, active INTEGER DEFAULT 1)''')
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS team_profiles
                         (id INTEGER PRIMARY KEY, name TEXT, title TEXT, skills TEXT, 
                          description TEXT, profile_url TEXT, hourly_rate TEXT, 
                          experience_years INTEGER, specialization TEXT, active INTEGER DEFAULT 1)''')        
        
        # Add missing columns to existing jobs table if they don't exist
        columns_to_add = [
            'rss_source_id INTEGER',
            'client_type TEXT',
            'client_name TEXT', 
            'client_company TEXT',
            'client_city TEXT',
            'client_country TEXT',
            'linkedin_url TEXT',
            'email TEXT',
            'phone TEXT',
            'whatsapp TEXT',
            'enriched INTEGER DEFAULT 0',
            'decision_maker TEXT',
            'skills TEXT',
            'categories TEXT',
            'hourly_rate TEXT',
            'site TEXT',
            'outreach_status TEXT DEFAULT \'Pending\'',
            'proposal_status TEXT DEFAULT \'Not Submitted\'',
            'submitted_by TEXT',
            'enriched_at TEXT',
            'enriched_by TEXT'
        ]
        
        # Commit table creation before checking counts
        conn.commit()
        
        for column in columns_to_add:
            try:
                c.execute(f'ALTER TABLE jobs ADD COLUMN {column}')
                conn.commit()
            except Exception as e:
                conn.rollback()  # Rollback failed transaction
                pass  # Column already exists
        
        # Insert team profiles from CSV data if none exists
        c.execute("SELECT COUNT(*) FROM team_profiles")
        if c.fetchone()[0] == 0:
            self.import_team_profiles(c, is_postgres)
            conn.commit()
        
        # Insert default RSS feeds if none exists
        c.execute("SELECT COUNT(*) FROM rss_feeds")
        if c.fetchone()[0] == 0:
            default_keyword_prompt = """
            Extract 2 specific app search terms from this job description for Google Play Store searching.
            Focus on the app's PURPOSE and USER NEED, not technical details.
            
            AVOID these technical/generic terms:
            - user-friendly interface, app design, app functionality, stable performance
            - efficient operation, user experience, mobile application, engagement
            - publishing, app development, full-stack development, mobile development
            - android, web, react, react native, flutter
            
            GOOD examples:
            - For wellness app: "wellness tracker", "meditation apps"
            - For AI health app: "health AI", "fitness assistant"
            - For expense tracking: "expense manager", "budget tracker"
            - For note taking: "note taking", "digital journal"
            
            Job: {job_description}
            
            Return exactly 2 specific search terms separated by comma:
            """
            
            default_proposal_prompt = """
            Generate a Proposalgenie-format proposal for this job:
            
            Job Title: {job_title}
            Job Description: {job_description}
            
            Work Examples: {examples_text}
            
            Follow the exact format:
            - Start with: {greeting}
            - Short intro with role + years + specialization
            - Paragraph 1: technical fit + expected result
            - Paragraph 2: Work examples (use the provided examples)
            - Paragraph 3: exactly 2 thoughtful developer/designer questions
            - Paragraph 4: CTA with call availability
            
            Use Unicode formatting, no markdown. Be conversational but professional.
            """
            
            default_olostep_prompt = """
            Find contact info for {search_target} in {city}, {country}. Get LinkedIn, email, phone, WhatsApp.
            """
            
            # Insert default RSS feeds
            if is_postgres:
                c.execute("""INSERT INTO rss_feeds 
                            (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                            VALUES (%s, %s, %s, %s, %s)""",
                         ("Web Development", "https://www.vollna.com/rss/Xnd57USkgSJf2jAewZTD",
                          default_keyword_prompt, default_proposal_prompt, default_olostep_prompt))
                
                c.execute("""INSERT INTO rss_feeds 
                            (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                            VALUES (%s, %s, %s, %s, %s)""",
                         ("Manual Jobs", "manual://jobs",
                          default_keyword_prompt, default_proposal_prompt, default_olostep_prompt))
            else:
                c.execute("""INSERT INTO rss_feeds 
                            (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                            VALUES (?, ?, ?, ?, ?)""",
                         ("Web Development", "https://www.vollna.com/rss/Xnd57USkgSJf2jAewZTD",
                          default_keyword_prompt, default_proposal_prompt, default_olostep_prompt))
                
                c.execute("""INSERT INTO rss_feeds 
                            (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                            VALUES (?, ?, ?, ?, ?)""",
                         ("Manual Jobs", "manual://jobs",
                          default_keyword_prompt, default_proposal_prompt, default_olostep_prompt))
            conn.commit()
        
        conn.close()
        
    def get_rss_feeds(self):
        conn = self.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM rss_feeds ORDER BY name")
        feeds = c.fetchall()
        conn.close()
        return feeds
    
    def get_jobs_by_rss(self, rss_id):
        conn = self.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        # Add missing columns if they don't exist (PostgreSQL should have them)
        if not is_postgres:
            for column in ['proposal_status TEXT DEFAULT "Not Submitted"', 'submitted_by TEXT']:
                try:
                    c.execute(f'ALTER TABLE jobs ADD COLUMN {column}')
                    conn.commit()
                except:
                    conn.rollback()
                    pass
        
        if is_postgres:
            c.execute("""SELECT id, title, description, url, client, budget, posted_date, processed,
                         client_type, client_name, client_company, client_city, client_country, 
                         linkedin_url, email, phone, whatsapp, enriched, decision_maker, skills, 
                         categories, hourly_rate, site, rss_source_id, outreach_status, 
                         proposal_status, submitted_by, enriched_at, enriched_by
                         FROM jobs WHERE rss_source_id = %s AND enriched != 1 
                         ORDER BY CAST(posted_date AS TIMESTAMP) DESC""", (rss_id,))
        else:
            c.execute("SELECT * FROM jobs WHERE rss_source_id = ? AND enriched != 1 ORDER BY datetime(posted_date) DESC", (rss_id,))
        jobs = c.fetchall()
        conn.close()
        return jobs
    
    def fetch_rss_jobs(self, rss_id, rss_url):
        try:
            feed = feedparser.parse(rss_url)
            new_jobs = 0
            
            conn = self.get_db_connection()
            c = conn.cursor()
            is_postgres = os.getenv('DATABASE_URL') is not None
            
            for entry in feed.entries:
                job_id = hashlib.md5(entry.link.encode()).hexdigest()
                
                if os.getenv('DATABASE_URL'):
                    c.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
                else:
                    c.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
                if not c.fetchone():
                    # Extract data from RSS
                    hourly_rate = 'Not specified'
                    if 'Hourly Rate:' in entry.title:
                        rate_part = entry.title.split('Hourly Rate:')[1].strip().rstrip(')')
                        hourly_rate = rate_part
                    
                    # Extract skills from description
                    skills = 'Not specified'
                    if 'Skills:' in entry.description:
                        skills_part = entry.description.split('Skills:')[1]
                        if 'Categories:' in skills_part:
                            skills_part = skills_part.split('Categories:')[0]
                        skills = skills_part.strip().replace(']]>', '').replace('<![CDATA[', '')
                    
                    # Extract categories
                    categories = 'Not specified'
                    if 'Categories:' in entry.description:
                        cat_part = entry.description.split('Categories:')[1]
                        categories = cat_part.strip().replace(']]>', '').replace('<![CDATA[', '')
                    
                    # Clean up description - get the main job description before Skills/Categories
                    description = entry.description
                    if 'Skills:' in description:
                        description = description.split('Skills:')[0].strip()
                    description = description.replace('<![CDATA[', '').replace(']]>', '').strip()
                    
                    print(f"RSS Job extracted - Skills: {skills}, Categories: {categories}, Description length: {len(description)}")
                    
                    if is_postgres:
                        c.execute("""INSERT INTO jobs 
                                    (id, title, description, url, client, budget, posted_date, 
                                     hourly_rate, skills, categories, rss_source_id)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                 (job_id, entry.title, description, entry.link,
                                  entry.get('author', 'Unknown'), 
                                  entry.get('budget', 'Not specified'),
                                  entry.get('published', datetime.now().isoformat()),
                                  hourly_rate, skills, categories, rss_id))
                    else:
                        c.execute("""INSERT INTO jobs 
                                    (id, title, description, url, client, budget, posted_date, 
                                     hourly_rate, skills, categories, rss_source_id)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                 (job_id, entry.title, description, entry.link,
                                  entry.get('author', 'Unknown'), 
                                  entry.get('budget', 'Not specified'),
                                  entry.get('published', datetime.now().isoformat()),
                                  hourly_rate, skills, categories, rss_id))
                    new_jobs += 1
            
            conn.commit()
            conn.close()
            return new_jobs
        except Exception as e:
            print(f"RSS fetch error for feed {rss_id}: {e}")
            return 0
    
    def start_rss_fetcher(self, rss_id, rss_url):
        def fetch_loop():
            while True:
                try:
                    # Check if feed is still active
                    conn = self.get_db_connection()
                    c = conn.cursor()
                    if os.getenv('DATABASE_URL'):
                        c.execute("SELECT active FROM rss_feeds WHERE id = %s", (rss_id,))
                    else:
                        c.execute("SELECT active FROM rss_feeds WHERE id = ?", (rss_id,))
                    result = c.fetchone()
                    conn.close()
                    
                    if result and result[0] == 1:  # Active
                        new_jobs = self.fetch_rss_jobs(rss_id, rss_url)
                        if new_jobs > 0:
                            print(f"RSS {rss_id}: Fetched {new_jobs} new jobs")
                    else:
                        print(f"RSS {rss_id}: Paused")
                        
                except Exception as e:
                    print(f"RSS {rss_id} fetch error: {e}")
                
                time.sleep(600)  # 10 minutes
        
        if rss_id not in self.rss_threads:
            thread = threading.Thread(target=fetch_loop, daemon=True)
            thread.start()
            self.rss_threads[rss_id] = thread
    
    def start_all_active_feeds(self):
        feeds = self.get_rss_feeds()
        for feed in feeds:
            if feed[3] == 1:  # Active
                self.start_rss_fetcher(feed[0], feed[2])
    
    def extract_keywords(self, job_description, rss_id):
        debug_log = []
        try:
            # Get custom prompt for this RSS feed
            conn = self.get_db_connection()
            c = conn.cursor()
            if os.getenv('DATABASE_URL'):
                c.execute("SELECT keyword_prompt FROM rss_feeds WHERE id = %s", (rss_id,))
            else:
                c.execute("SELECT keyword_prompt FROM rss_feeds WHERE id = ?", (rss_id,))
            prompt_template = c.fetchone()[0]
            conn.close()
            
            prompt = prompt_template.format(job_description=job_description)
            
            debug_log.append("Starting keyword extraction...")
            debug_log.append("Calling OpenAI for keyword extraction...")
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            keywords = response.choices[0].message.content.strip().split(',')
            result = [k.strip() for k in keywords[:2]]
            debug_log.append(f"Keywords extracted: {result}")
            return result, debug_log
        except Exception as e:
            debug_log.append(f"Keyword extraction failed: {str(e)}")
            result = random.sample(GENERIC_KEYWORDS, 2)
            debug_log.append(f"Using fallback keywords: {result}")
            return result, debug_log
    
    def generate_proposal(self, job_title, job_description, examples, client_first_name, rss_id):
        debug_log = []
        
        # Get custom prompt for this RSS feed
        conn = self.get_db_connection()
        c = conn.cursor()
        if os.getenv('DATABASE_URL'):
            c.execute("SELECT proposal_prompt FROM rss_feeds WHERE id = %s", (rss_id,))
        else:
            c.execute("SELECT proposal_prompt FROM rss_feeds WHERE id = ?", (rss_id,))
        prompt_template = c.fetchone()[0]
        conn.close()
        
        examples_text = ""
        if examples:
            examples_text = "𝐖𝐨𝐫𝐤 𝐞𝐱𝐚𝐦𝐩𝐥𝐞𝐬:\n\n"
            for i, ex in enumerate(examples, 1):
                examples_text += f"{i}. {ex['name']}: {ex['description']} ({ex['url']})\n\n"
            debug_log.append(f"Added {len(examples)} work examples to proposal")
        else:
            debug_log.append("No work examples available")
        
        greeting = f"◕‿◕ 🙋♂️ Hello {client_first_name}" if client_first_name else "◕‿◕ 🙋♂️ Hello there"
        debug_log.append(f"Using greeting: {greeting}")
        
        prompt = prompt_template.format(
            job_title=job_title,
            job_description=job_description,
            examples_text=examples_text,
            greeting=greeting
        )
        
        try:
            debug_log.append("Calling OpenAI for proposal generation...")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000
            )
            proposal = response.choices[0].message.content.strip()
            debug_log.append("Proposal generated successfully")
            return proposal, debug_log
        except Exception as e:
            debug_log.append(f"Proposal generation failed: {str(e)}")
            return f"Error generating proposal: {e}", debug_log
    
    def get_work_examples(self, keywords):
        """Get work examples from Google Play Store"""
        try:
            from google_play_scraper import search
            print(f"Google Play Scraper imported successfully")
        except ImportError:
            print("ERROR: google-play-scraper not installed")
            return self.get_fallback_examples(keywords)
        
        examples = []
        print(f"Searching Google Play Store with keywords: {keywords}")
        
        # Search each keyword
        for i, keyword in enumerate(keywords[:2]):
            try:
                print(f"Searching keyword {i+1}: '{keyword}'")
                
                # Try multiple countries to get results
                countries = ['us', 'sg', 'in', 'gb']
                apps_found = []
                
                for country in countries:
                    try:
                        results = search(
                            keyword,
                            lang="en",
                            country=country,
                            n_hits=10
                        )
                        
                        if results:
                            print(f"Found {len(results)} results for '{keyword}' in {country}")
                            
                            for app in results:
                                try:
                                    score = app.get('score') or 0
                                    if score >= 3.0:  # Only good rated apps
                                        app_data = {
                                            'name': app.get('title', 'Unknown App'),
                                            'description': str(app.get('description', 'No description'))[:200] + '...',
                                            'url': f"https://play.google.com/store/apps/details?id={app.get('appId', '')}",
                                            'installs': str(app.get('installs', '0')),
                                            'score': score
                                        }
                                        apps_found.append(app_data)
                                except Exception as e:
                                    continue
                            
                            if len(apps_found) >= 5:  # Got enough apps
                                break
                                
                    except Exception as e:
                        print(f"Error searching {country}: {e}")
                        continue
                
                # Add 5 apps per keyword
                keyword_apps = apps_found[:5]
                examples.extend(keyword_apps)
                print(f"Added {len(keyword_apps)} real apps for '{keyword}'")
                
            except Exception as e:
                print(f"Error with keyword '{keyword}': {e}")
        
        # If we got real apps, return them
        if examples:
            examples.sort(key=lambda x: x['score'], reverse=True)
            print(f"Returning {len(examples)} real Google Play Store apps")
            return examples[:10]
        
        # Fallback if no real apps found
        print("No real apps found, using fallback")
        return self.get_fallback_examples(keywords)
    
    def get_fallback_examples(self, keywords):
        """Fallback examples when Google Play Store fails"""
        return [
            {
                'name': 'ChatGPT',
                'description': 'The official ChatGPT app by OpenAI. Get instant answers, find creative inspiration, learn something new...',
                'url': 'https://play.google.com/store/apps/details?id=com.openai.chatgpt',
                'installs': '50,000,000+',
                'score': 4.5
            },
            {
                'name': 'Google Assistant',
                'description': 'Meet your Google Assistant. Ask it questions. Tell it to do things. It is your own personal Google...',
                'url': 'https://play.google.com/store/apps/details?id=com.google.android.apps.googleassistant',
                'installs': '1,000,000,000+',
                'score': 4.1
            },
            {
                'name': 'Replika: My AI Friend',
                'description': 'Replika is an AI companion who is eager to learn and would love to see the world through your eyes...',
                'url': 'https://play.google.com/store/apps/details?id=ai.replika.app',
                'installs': '10,000,000+',
                'score': 4.2
            },
            {
                'name': 'Speechify Text to Speech Voice',
                'description': 'Listen to docs, articles, PDFs, email — anything you read — by adding audio to any text with Speechify...',
                'url': 'https://play.google.com/store/apps/details?id=com.cliffweitzman.speechify2',
                'installs': '5,000,000+',
                'score': 4.4
            },
            {
                'name': 'Voice Recorder',
                'description': 'Simple and reliable voice recorder that allows you to record voice memos and important meetings...',
                'url': 'https://play.google.com/store/apps/details?id=com.media.bestrecorder.audiorecorder',
                'installs': '100,000,000+',
                'score': 4.6
            }
        ]
    
    def import_team_profiles(self, cursor, is_postgres=False):
        """Import team profiles from CSV data"""
        profiles = [
            ("Sachin M.", "Full Stack Developer | Senior .Net Developer", "MySQL, Web Application, CMS Framework, ASP.NET, .NET Framework, .NET Compact Framework, .NET Core", "Strong experience in system analysis, architecture, development, object-oriented design, system integration and leadership. Proficient with the Microsoft .NET Framework, PHP, Android, DynamicAX, PowerBI and SQL development.", "https://www.upwork.com/freelancers/~015184bacbca7a5bfb/", "$25-50/hr", 6, ".NET Development"),
            ("Neha V.", "Full Stack Web and Mobile App Development | AI Chatbot & Voice Agent", "AI Chatbot, Artificial Intelligence, Python, Full-Stack Development, ChatGPT, Web Application, Mobile App, AI Agent Development, OpenAPI, ChatGPT API Integration, Mobile App Development, Web Application Development, React Native, React, Node.js", "Full stack developer with 5+ years of experience building modern web and mobile applications, as well as integrating AI-driven chatbots and voice agents into business workflows.", "https://www.upwork.com/freelancers/~016a3078041587aff0/", "$30-60/hr", 5, "AI & Mobile Development"),
            ("Shobhit S.", "Full Stack Developer | PHP | Angular | .NET |", "PHP, API Integration, Web Development, JavaScript, Mobile App Design, Mobile App, ASP.NET, .NET Framework, .NET Core, Angular, PHP Script", "5+ years of experience in Web app development, creating apps, bug fixing existing apps and collaborating on major projects.", "https://www.upwork.com/freelancers/~014d96f12f06a545bb/", "$20-40/hr", 5, "PHP & Angular Development"),
            ("Aditya S.", "Mobile App Developer | React Native | Flutter | React Native Expo", "Hybrid App Development, Firebase Realtime Database, Firebase, React, React Native, API, ChatGPT, Google Maps API, Responsive Design, FinTech, Flutter, Mobile App Development, Android, iOS, NFC", "Top Rated Plus Mobile App Developer with 7+ years of experience in mobile app development, specializing in Healthcare & Fintech applications.", "https://www.upwork.com/freelancers/~016487ec9f3aab93c4/", "$35-65/hr", 7, "Healthcare & Fintech Mobile Apps"),
            ("Tahir S.", "Mobile App Developer | iOS | Android", "Node.js, PostgreSQL, MySQL, Database, Web Development, NodeJS Framework, React, Redux, Web Application Development, Web Application, Angular, ChatGPT", "Mobile Developer with 5+ years experience in Mobile Development with Swift, SwiftUI, Java/Kotlin, React Native and Flutter.", "https://www.upwork.com/freelancers/~01ca241aae4f03b625/", "$25-45/hr", 5, "Native Mobile Development"),
            ("Adnan K.", "Automation Expert | Zapier, Make.com, n8n", "Zapier, Automation, Make.com, n8n, CRM Automation, Task Automation, System Automation", "Certified specialist in Zapier, Make.com, and a variety of CRMs with over 5+ years of experience as a senior software engineer.", "https://www.upwork.com/freelancers/~01635ad8021d6f9378/", "$30-50/hr", 5, "Automation & CRM Integration"),
            ("Vishakha S.", "Full Stack / AI-ML expert/ Python/ OpenCV/ ChatGPT/ OpenAI", "API Integration, Python, Web Development, PHP Script, Web Design, API, Artificial Intelligence, Machine Learning, TensorFlow, Golang, Full-Stack Development", "Python developer and Data Scientist with 3+ years experience in Artificial intelligence, Machine learning and Deep learning.", "https://www.upwork.com/freelancers/~018df5a16e04c63804/", "$25-45/hr", 3, "AI/ML & Python Development"),
            ("Anurag K.", "Full Stack Mobile App Developer | UI/UX Design | Hybrid App Dev.", "Hybrid App Development, React Native, React, iOS Development,Android App Development, Flutter, Payment Functionality, API Integration, Responsive Design, Front-End Development, Expo.io, Database, API", "Full Stack Mobile App Developer with 4+ years of experience turning ideas into high-performing mobile applications.", "https://www.upwork.com/freelancers/~0131ec49a5a4bbad75/", "$25-50/hr", 4, "Hybrid Mobile App Development"),
            ("Vedika P.", "WordPress | WooCommerce | Themes & Plugins Development", "API Integration, Responsive Design, WordPress, WooCommerce, WordPress Theme, WordPress Plugin, WordPress Website, WordPress e-Commerce, WordPress SEO Plugin, WordPress Development", "WordPress and WooCommerce expert with over 4 years of experience helping businesses create and grow their online marketplaces.", "https://www.upwork.com/freelancers/~011e78b81a5d7fbd59/", "$20-35/hr", 4, "WordPress & WooCommerce Development"),
            ("Manmeet S.", "Facebook Certified Ads Specialist | SEO Specialist | Instagram Ads", "Facebook Ads Manager, Facebook Ad Campaign, Facebook Advertising, Digital Marketing, Social Media Advertising, Google Ads, SEO Plugin, Search Engine Optimization", "Certified Facebook Ads expert, Google Ads Specialist, and Digital Marketing strategist with proven track record of 5x-8x growth.", "https://www.upwork.com/freelancers/~0185aeba872197bac6/", "$25-45/hr", 5, "Digital Marketing & Ads")
        ]
        
        for profile in profiles:
            if is_postgres:
                cursor.execute("""INSERT INTO team_profiles 
                                (name, title, skills, description, profile_url, hourly_rate, experience_years, specialization)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", profile)
            else:
                cursor.execute("""INSERT INTO team_profiles 
                                (name, title, skills, description, profile_url, hourly_rate, experience_years, specialization)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", profile)
    
    def get_team_profiles(self):
        conn = self.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM team_profiles ORDER BY name")
        profiles = c.fetchall()
        conn.close()
        return profiles
    
    def match_job_to_team(self, job_description, job_skills):
        """Match job requirements to team member skills"""
        profiles = self.get_team_profiles()
        matches = []
        
        job_text = (job_description + " " + job_skills).lower()
        
        for profile in profiles:
            # profile columns: id, name, title, skills, description, profile_url, hourly_rate, experience_years, specialization, active
            if profile[9] == 0:  # Skip inactive profiles (active column)
                continue
                
            profile_skills = profile[3].lower()  # skills column
            profile_desc = profile[4].lower()    # description column
            
            # Simple keyword matching
            skill_matches = 0
            skill_keywords = profile_skills.split(', ')
            
            for skill in skill_keywords:
                if skill.strip() in job_text:
                    skill_matches += 1
            
            if skill_matches > 0:
                match_score = (skill_matches / len(skill_keywords)) * 100
                matches.append({
                    'profile': profile,
                    'match_score': round(match_score, 1),
                    'matched_skills': skill_matches
                })
        
        # Sort by match score
        matches.sort(key=lambda x: x['match_score'], reverse=True)
        return matches[:3]  # Top 3 matches

# Initialize system
system = MultiRSSProposalSystem()

# Authentication decorator
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = system.get_db_connection()
        c = conn.cursor()
        if os.getenv('DATABASE_URL'):
            c.execute("SELECT * FROM users WHERE email = %s AND password = %s AND active = 1", (email, password))
        else:
            c.execute("SELECT * FROM users WHERE email = ? AND password = ? AND active = 1", (email, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            session['user_email'] = email
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    feeds = system.get_rss_feeds()
    return render_template('multi_rss_index.html', feeds=feeds)

@app.route('/rss/<int:rss_id>')
@login_required
def rss_jobs(rss_id):
    feeds = system.get_rss_feeds()
    jobs = system.get_jobs_by_rss(rss_id)
    current_feed = next((f for f in feeds if f[0] == rss_id), None)
    return render_template('rss_jobs.html', feeds=feeds, jobs=jobs, current_feed=current_feed)

@app.route('/rss/chrome')
@login_required
def chrome_jobs():
    feeds = system.get_rss_feeds()
    # Find Manual Jobs RSS feed (Chrome extension uses this)
    manual_feed = next((f for f in feeds if f[1] == "Manual Jobs"), None)
    if manual_feed:
        jobs = system.get_jobs_by_rss(manual_feed[0])
        return render_template('rss_jobs.html', feeds=feeds, jobs=jobs, current_feed=manual_feed)
    else:
        return "Chrome extension RSS feed not found", 404

@app.route('/admin')
@login_required
def admin():
    feeds = system.get_rss_feeds()
    return render_template('admin.html', feeds=feeds)

@app.route('/team-management')
@login_required
def team_management():
    profiles = system.get_team_profiles()
    return render_template('team_management.html', profiles=profiles)

@app.route('/enriched-jobs')
@login_required
def enriched_jobs():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Order by posted_date since enriched_at column doesn't exist in PostgreSQL yet
    if is_postgres:
        c.execute("""SELECT id, title, description, url, client, budget, posted_date, processed,
                     client_type, client_name, client_company, client_city, client_country, 
                     linkedin_url, email, phone, whatsapp, enriched, decision_maker, skills, 
                     categories, hourly_rate, site, rss_source_id, outreach_status, 
                     proposal_status, submitted_by, enriched_at, enriched_by
                     FROM jobs WHERE enriched = 1 ORDER BY CAST(posted_date AS TIMESTAMP) DESC""")
    else:
        c.execute("SELECT * FROM jobs WHERE enriched = 1 ORDER BY datetime(posted_date) DESC")
    jobs = c.fetchall()
    conn.close()
    return render_template('enriched_jobs.html', jobs=jobs)

@app.route('/api/job-matcher', methods=['POST'])
def job_matcher():
    data = request.json
    job_description = data.get('job_description', '')
    job_skills = data.get('job_skills', '')
    
    matches = system.match_job_to_team(job_description, job_skills)
    
    return jsonify({
        'success': True,
        'matches': matches
    })

@app.route('/add_profile', methods=['POST'])
def add_profile():
    data = request.json
    
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("""INSERT INTO team_profiles 
                    (name, title, skills, description, profile_url, hourly_rate, experience_years, specialization, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                 (data['name'], data['title'], data['skills'], data['description'],
                  data['profile_url'], data['hourly_rate'], data['experience_years'],
                  data['specialization'], data['active']))
    else:
        c.execute("""INSERT INTO team_profiles 
                    (name, title, skills, description, profile_url, hourly_rate, experience_years, specialization, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (data['name'], data['title'], data['skills'], data['description'],
                  data['profile_url'], data['hourly_rate'], data['experience_years'],
                  data['specialization'], data['active']))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/update_profile/<int:profile_id>', methods=['POST'])
def update_profile(profile_id):
    data = request.json
    
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("""UPDATE team_profiles SET 
                    name = %s, title = %s, skills = %s, description = %s, 
                    profile_url = %s, hourly_rate = %s, experience_years = %s, 
                    specialization = %s, active = %s
                    WHERE id = %s""",
                 (data['name'], data['title'], data['skills'], data['description'],
                  data['profile_url'], data['hourly_rate'], data['experience_years'],
                  data['specialization'], data['active'], profile_id))
    else:
        c.execute("""UPDATE team_profiles SET 
                    name = ?, title = ?, skills = ?, description = ?, 
                    profile_url = ?, hourly_rate = ?, experience_years = ?, 
                    specialization = ?, active = ?
                    WHERE id = ?""",
                 (data['name'], data['title'], data['skills'], data['description'],
                  data['profile_url'], data['hourly_rate'], data['experience_years'],
                  data['specialization'], data['active'], profile_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/add_rss', methods=['POST'])
def add_rss():
    data = request.json
    
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    if is_postgres:
        c.execute("""INSERT INTO rss_feeds (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                     VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                 (data['name'], data['url'], data['keyword_prompt'], 
                  data['proposal_prompt'], data['olostep_prompt']))
        rss_id = c.fetchone()[0]
    else:
        c.execute("""INSERT INTO rss_feeds (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                     VALUES (?, ?, ?, ?, ?)""",
                 (data['name'], data['url'], data['keyword_prompt'], 
                  data['proposal_prompt'], data['olostep_prompt']))
        rss_id = c.lastrowid
    
    conn.commit()
    conn.close()
    
    # Start fetcher for new RSS
    system.start_rss_fetcher(rss_id, data['url'])
    
    return jsonify({'success': True, 'rss_id': rss_id})

@app.route('/toggle_rss/<int:rss_id>', methods=['POST'])
def toggle_rss(rss_id):
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("UPDATE rss_feeds SET active = 1 - active WHERE id = %s", (rss_id,))
        c.execute("SELECT active FROM rss_feeds WHERE id = %s", (rss_id,))
    else:
        c.execute("UPDATE rss_feeds SET active = 1 - active WHERE id = ?", (rss_id,))
        c.execute("SELECT active FROM rss_feeds WHERE id = ?", (rss_id,))
    new_status = c.fetchone()[0]
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'active': new_status})

@app.route('/update_prompts/<int:rss_id>', methods=['POST'])
def update_prompts(rss_id):
    data = request.json
    
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("""UPDATE rss_feeds SET 
                     keyword_prompt = %s, proposal_prompt = %s, olostep_prompt = %s
                     WHERE id = %s""",
                 (data['keyword_prompt'], data['proposal_prompt'], 
                  data['olostep_prompt'], rss_id))
    else:
        c.execute("""UPDATE rss_feeds SET 
                     keyword_prompt = ?, proposal_prompt = ?, olostep_prompt = ?
                     WHERE id = ?""",
                 (data['keyword_prompt'], data['proposal_prompt'], 
                  data['olostep_prompt'], rss_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/generate_proposal', methods=['POST'])
def generate_proposal():
    data = request.json
    job_id = data['job_id']
    rss_id = data['rss_id']
    
    # Get job details
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
    else:
        c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = c.fetchone()
    conn.close()
    
    if not job:
        return jsonify({'error': 'Job not found'})
    
    try:
        # Extract keywords and generate proposal
        keywords, debug_log = system.extract_keywords(job[2], rss_id)
        examples = system.get_work_examples(keywords)
        
        client_first_name = job[9] or job[16] or 'there'
        if client_first_name != 'there':
            client_first_name = client_first_name.split()[0]
        
        proposal, proposal_debug = system.generate_proposal(job[1], job[2], examples, client_first_name, rss_id)
        debug_log.extend(proposal_debug)
        
        # Save proposal
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        if is_postgres:
            # Check if proposal exists, update or insert
            c.execute("SELECT id FROM proposals WHERE job_id = %s", (job_id,))
            existing = c.fetchone()
            
            if existing:
                c.execute("""UPDATE proposals SET 
                            proposal = %s, examples = %s, created_at = %s, debug_log = %s
                            WHERE job_id = %s""",
                         (proposal, json.dumps(examples), datetime.now().isoformat(), 
                          json.dumps(debug_log), job_id))
            else:
                c.execute("""INSERT INTO proposals 
                            (job_id, proposal, examples, created_at, debug_log)
                            VALUES (%s, %s, %s, %s, %s)""",
                         (job_id, proposal, json.dumps(examples), datetime.now().isoformat(), 
                          json.dumps(debug_log)))
            c.execute("UPDATE jobs SET processed = 1 WHERE id = %s", (job_id,))
        else:
            c.execute("""INSERT OR REPLACE INTO proposals 
                        (job_id, proposal, examples, created_at, debug_log)
                        VALUES (?, ?, ?, ?, ?)""",
                     (job_id, proposal, json.dumps(examples), datetime.now().isoformat(), 
                      json.dumps(debug_log)))
            c.execute("UPDATE jobs SET processed = 1 WHERE id = ?", (job_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'proposal': proposal,
            'examples': examples,
            'keywords': keywords,
            'debug_log': debug_log
        })
    except Exception as e:
        return jsonify({'error': str(e), 'debug_log': [f'Error: {str(e)}']})

@app.route('/enrich_client', methods=['POST'])
def enrich_client():
    try:
        data = request.json
        print(f"Received enrichment data: {data}")
        
        job_id = data['job_id']
        rss_id = data['rss_id']
        enrichment_author = data.get('enrichment_author', 'Unknown')
        
        # Check if required fields exist
        print(f"Received data keys: {list(data.keys())}")
        if 'client_city' not in data:
            return jsonify({'success': False, 'error': 'client_city missing from request'})
        if 'client_country' not in data:
            return jsonify({'success': False, 'error': 'client_country missing from request'})
        
        company_name = data.get('client_company', '').strip()
        person_name = data.get('client_name', '').strip()
        city = data.get('client_city', '')
        country = data.get('client_country', '')
        
        if not company_name and not person_name:
            return jsonify({'success': False, 'error': 'Either company name or person name is required'})
        
        # Create appropriate prompt based on what's provided
        if company_name and not person_name:
            # Company search - find CEO/founder/owner
            prompt = f"Find CEO/founder/owner/self-employed person of {company_name} in {city}, {country}. Get full name, company name, LinkedIn, email, phone, WhatsApp."
            search_target = company_name
        else:
            # Person search (either person name only, or both company and person provided)
            if person_name:
                prompt = f"Find contact info for {person_name} in {city}, {country}. Get full name, company name, LinkedIn, email, phone, WhatsApp."
                search_target = person_name
            else:
                return jsonify({'success': False, 'error': 'Person name is required'})
        
        print(f"Search type: {'Company' if company_name and not person_name else 'Person'}")
        print(f"Search target: {search_target}")
        print(f"Prompt: {prompt}")
        
        # Call Olostep API using the working endpoint and format
        prompt_data = {
            "task": prompt,
            "json": {
                "full_name": "",
                "company_name": "",
                "linkedin_url": "",
                "primary_email": "",
                "phone_number": "",
                "whatsapp_number": ""
            }
        }
        
        try:
            response = requests.post(
                'https://api.olostep.com/v1/answers',
                headers={'Authorization': f'Bearer {OLOSTEP_KEY}', 'Content-Type': 'application/json'},
                json=prompt_data,
                timeout=60
            )
            
            print(f"Olostep API response status: {response.status_code}")
            print(f"Olostep API response: {response.text}")
            
            if response.status_code == 200:
                api_response = response.json()
                # Extract data using the working script format
                if api_response and 'result' in api_response and 'json_content' in api_response['result']:
                    api_data = json.loads(api_response['result']['json_content'])
                    result = {
                        'found_name': api_data.get('full_name', ''),
                        'found_company': api_data.get('company_name', ''),
                        'linkedin': api_data.get('linkedin_url', ''),
                        'email': api_data.get('primary_email', ''),
                        'phone': api_data.get('phone_number', ''),
                        'whatsapp': api_data.get('whatsapp_number', '')
                    }
                else:
                    result = {'found_name': '', 'found_company': '', 'linkedin': '', 'email': '', 'phone': '', 'whatsapp': ''}
            else:
                # Return empty data when API fails so user can fill manually
                result = {
                    'found_name': '',
                    'found_company': '',
                    'linkedin': '',
                    'email': '',
                    'phone': '',
                    'whatsapp': ''
                }
                print("API failed - job moved to enriched tab for manual completion")
        except Exception as api_error:
            print(f"Olostep API error: {api_error}")
            # Return empty data so user can fill manually
            result = {
                'found_name': '',
                'found_company': '',
                'linkedin': '',
                'email': '',
                'phone': '',
                'whatsapp': ''
            }
        
        # Use found names if original fields were empty
        final_person_name = person_name or result.get('found_name', '')
        final_company_name = company_name or result.get('found_company', '')
        
        # Update job with enrichment data using your existing schema
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        # Add columns if they don't exist (skip for PostgreSQL as they should exist)
        if not is_postgres:
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN enriched_at TEXT')
            except:
                pass  # Column already exists
            
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN outreach_status TEXT DEFAULT "Pending"')
            except:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN proposal_status TEXT DEFAULT "Not Submitted"')
            except:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN submitted_by TEXT')
            except:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN enriched_by TEXT')
            except:
                pass  # Column already exists
        
        if is_postgres:
            c.execute("""UPDATE jobs SET 
                        client_name = %s, client_company = %s, 
                        client_city = %s, client_country = %s, linkedin_url = %s, 
                        email = %s, phone = %s, whatsapp = %s, enriched = 1,
                        decision_maker = %s, enriched_by = %s
                        WHERE id = %s""",
                     (final_person_name, final_company_name, 
                      city, country, result.get('linkedin', ''), 
                      result.get('email', ''), result.get('phone', ''), 
                      result.get('whatsapp', ''), search_target, enrichment_author, job_id))
        else:
            c.execute("""UPDATE jobs SET 
                        client_name = ?, client_company = ?, 
                        client_city = ?, client_country = ?, linkedin_url = ?, 
                        email = ?, phone = ?, whatsapp = ?, enriched = 1,
                        decision_maker = ?, enriched_by = ?, enriched_at = ?
                        WHERE id = ?""",
                     (final_person_name, final_company_name, 
                      city, country, result.get('linkedin', ''), 
                      result.get('email', ''), result.get('phone', ''), 
                      result.get('whatsapp', ''), search_target, enrichment_author, 
                      datetime.now().isoformat(), job_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'enrichment': {
                'linkedin_url': result.get('linkedin', ''),
                'email': result.get('email', ''),
                'phone': result.get('phone', ''),
                'whatsapp': result.get('whatsapp', ''),
                'decision_maker': search_target
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



# API endpoints for Chrome plugin integration
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("SELECT * FROM users WHERE email = %s AND password = %s AND active = 1", (email, password))
    else:
        c.execute("SELECT * FROM users WHERE email = ? AND password = ? AND active = 1", (email, password))
    user = c.fetchone()
    conn.close()
    
    if user:
        session['user_email'] = email
        return jsonify({'success': True, 'message': 'Login successful'})
    else:
        return jsonify({'success': False, 'error': 'Invalid credentials'})

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    if 'user_email' in session:
        return jsonify({'authenticated': True, 'email': session['user_email']})
    else:
        return jsonify({'authenticated': False})

@app.route('/api/check-job', methods=['POST'])
def check_job():
    # Allow Chrome extension requests
    if 'user_email' not in session and request.headers.get('X-Chrome-Extension') != 'mindwork':
        return jsonify({'error': 'Authentication required'}), 401
        
    data = request.json
    job_url = data.get('url')
    
    conn = system.get_db_connection()
    c = conn.cursor()
    if os.getenv('DATABASE_URL'):
        c.execute("SELECT id FROM jobs WHERE url = %s", (job_url,))
    else:
        c.execute("SELECT id FROM jobs WHERE url = ?", (job_url,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return jsonify({'exists': True, 'jobId': result[0]})
    else:
        return jsonify({'exists': False})

@app.route('/api/rss-feeds', methods=['GET'])
def get_rss_feeds_api():
    # Allow Chrome extension requests
    if 'user_email' not in session and request.headers.get('X-Chrome-Extension') != 'mindwork':
        return jsonify({'error': 'Authentication required'}), 401
        
    try:
        feeds = system.get_rss_feeds()
        feed_list = []
        for feed in feeds:
            feed_list.append({
                'id': feed[0],
                'name': feed[1],
                'url': feed[2],
                'active': feed[3]
            })
        return jsonify({'success': True, 'feeds': feed_list})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/create-job', methods=['POST'])
def create_job():
    # Allow Chrome extension requests
    if 'user_email' not in session and request.headers.get('X-Chrome-Extension') != 'mindwork':
        return jsonify({'error': 'Authentication required'}), 401
        
    data = request.json
    print(f"Received job data: {data}")
    
    # Generate job ID from URL
    job_id = hashlib.md5(data['url'].encode()).hexdigest()
    
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        # Use provided RSS ID or default to Manual Jobs
        rss_id = data.get('rss_id')
        if not rss_id:
            if is_postgres:
                c.execute("SELECT id FROM rss_feeds WHERE name = %s LIMIT 1", ('Manual Jobs',))
            else:
                c.execute("SELECT id FROM rss_feeds WHERE name = ? LIMIT 1", ('Manual Jobs',))
            result = c.fetchone()
            if result:
                rss_id = result[0]
        
        if is_postgres:
            c.execute("""INSERT INTO jobs 
                        (id, title, description, url, client, budget, posted_date, 
                         hourly_rate, skills, categories, rss_source_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (job_id, data.get('title', ''), data.get('description', ''), 
                      data['url'], data.get('client', 'Unknown'), data.get('budget', 'Not specified'),
                      data.get('posted_date', datetime.now().isoformat()), 
                      data.get('hourly_rate', 'Not specified'), data.get('skills', 'Not specified'),
                      data.get('categories', 'Not specified'), rss_id))
        else:
            c.execute("""INSERT INTO jobs 
                        (id, title, description, url, client, budget, posted_date, 
                         hourly_rate, skills, categories, rss_source_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (job_id, data.get('title', ''), data.get('description', ''), 
                      data['url'], data.get('client', 'Unknown'), data.get('budget', 'Not specified'),
                      data.get('posted_date', datetime.now().isoformat()), 
                      data.get('hourly_rate', 'Not specified'), data.get('skills', 'Not specified'),
                      data.get('categories', 'Not specified'), rss_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'jobId': job_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/job/<job_id>')
def job_detail(job_id):
    # Redirect to Manual Jobs RSS feed for Chrome plugin jobs
    feeds = system.get_rss_feeds()
    manual_feed = next((f for f in feeds if f[1] == "Manual Jobs"), None)
    
    if manual_feed:
        return redirect(f'/rss/{manual_feed[0]}?highlight={job_id}')
    elif feeds:
        return redirect(f'/rss/{feeds[0][0]}?highlight={job_id}')
    else:
        return "No RSS feeds configured", 404

@app.route('/update_job_status', methods=['POST'])
def update_job_status():
    """Update only the status fields without touching enrichment data"""
    try:
        data = request.json
        job_id = data['job_id']
        proposal_status = data.get('proposal_status', 'Not Submitted')
        submitted_by = data.get('submitted_by', '')
        outreach_status = data.get('outreach_status', 'Pending')
        
        print(f"[UPDATE_JOB_STATUS] Job: {job_id}, Proposal: {proposal_status}, By: {submitted_by}, Outreach: {outreach_status}")
        
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        if is_postgres:
            c.execute("""UPDATE jobs SET 
                        proposal_status=%s, submitted_by=%s, outreach_status=%s
                        WHERE id=%s""",
                     (proposal_status, submitted_by, outreach_status, job_id))
        else:
            c.execute("""UPDATE jobs SET 
                        proposal_status=?, submitted_by=?, outreach_status=?
                        WHERE id=?""",
                     (proposal_status, submitted_by, outreach_status, job_id))
        
        rows_affected = c.rowcount
        conn.commit()
        
        print(f"[UPDATE_JOB_STATUS] Updated {rows_affected} rows")
        
        # Verify
        if is_postgres:
            c.execute("SELECT proposal_status, submitted_by, outreach_status FROM jobs WHERE id=%s", (job_id,))
        else:
            c.execute("SELECT proposal_status, submitted_by, outreach_status FROM jobs WHERE id=?", (job_id,))
        
        result = c.fetchone()
        print(f"[UPDATE_JOB_STATUS] Verified values: {result}")
        
        conn.close()
        
        return jsonify({
            'success': True,
            'rows_affected': rows_affected,
            'updated_values': {
                'proposal_status': result[0] if result else None,
                'submitted_by': result[1] if result else None,
                'outreach_status': result[2] if result else None
            }
        })
    except Exception as e:
        print(f"[UPDATE_JOB_STATUS] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/update_enrichment', methods=['POST'])
def update_enrichment():
    try:
        data = request.json
        job_id = data['job_id']
        
        print(f"[UPDATE_ENRICHMENT] Received data for job {job_id}: {data}")
        
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        # Add columns if they don't exist (PostgreSQL should have them)
        if not is_postgres:
            for column in ['outreach_status TEXT DEFAULT "Pending"', 'proposal_status TEXT DEFAULT "Not Submitted"', 'submitted_by TEXT']:
                try:
                    c.execute(f'ALTER TABLE jobs ADD COLUMN {column}')
                    conn.commit()
                except:
                    conn.rollback()
                    pass
        
        # Build UPDATE query dynamically to only update provided fields
        update_fields = []
        update_values = []
        
        # Map of field names to data keys
        field_mapping = {
            'client_name': 'client_name',
            'client_company': 'client_company',
            'client_city': 'client_city',
            'client_country': 'client_country',
            'linkedin_url': 'linkedin_url',
            'email': 'email',
            'phone': 'phone',
            'whatsapp': 'whatsapp',
            'decision_maker': 'decision_maker',
            'outreach_status': 'outreach_status',
            'proposal_status': 'proposal_status',
            'submitted_by': 'submitted_by'
        }
        
        # Only include fields that are present in the request
        for db_field, data_key in field_mapping.items():
            if data_key in data:
                update_fields.append(db_field)
                update_values.append(data[data_key])
        
        if not update_fields:
            conn.close()
            return jsonify({'success': False, 'error': 'No fields to update'})
        
        # Add job_id to the end
        update_values.append(job_id)
        
        if is_postgres:
            placeholders = ', '.join([f"{field}=%s" for field in update_fields])
            query = f"UPDATE jobs SET {placeholders} WHERE id=%s"
        else:
            placeholders = ', '.join([f"{field}=?" for field in update_fields])
            query = f"UPDATE jobs SET {placeholders} WHERE id=?"
        
        print(f"[UPDATE_ENRICHMENT] Query: {query}")
        print(f"[UPDATE_ENRICHMENT] Values: {update_values}")
        
        c.execute(query, tuple(update_values))
        rows_affected = c.rowcount
        
        conn.commit()
        print(f"[UPDATE_ENRICHMENT] Updated {rows_affected} rows for job {job_id}")
        
        # Verify the update
        if is_postgres:
            c.execute("SELECT proposal_status, submitted_by, outreach_status FROM jobs WHERE id=%s", (job_id,))
        else:
            c.execute("SELECT proposal_status, submitted_by, outreach_status FROM jobs WHERE id=?", (job_id,))
        
        result = c.fetchone()
        print(f"[UPDATE_ENRICHMENT] Verification - Current values: {result}")
        
        conn.close()
        
        return jsonify({
            'success': True, 
            'rows_affected': rows_affected,
            'current_values': {
                'proposal_status': result[0] if result else None,
                'submitted_by': result[1] if result else None,
                'outreach_status': result[2] if result else None
            }
        })
    except Exception as e:
        print(f"[UPDATE_ENRICHMENT] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_job/<job_id>', methods=['POST'])
def delete_job(job_id):
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        
        # Delete job and related proposals
        if os.getenv('DATABASE_URL'):
            c.execute("DELETE FROM proposals WHERE job_id = %s", (job_id,))
            c.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        else:
            c.execute("DELETE FROM proposals WHERE job_id = ?", (job_id,))
            c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/create-manual-feed', methods=['POST'])
def create_manual_feed():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Check if Manual Jobs already exists
    if is_postgres:
        c.execute("SELECT id FROM rss_feeds WHERE name = %s", ('Manual Jobs',))
    else:
        c.execute("SELECT id FROM rss_feeds WHERE name = ?", ('Manual Jobs',))
    if c.fetchone():
        conn.close()
        return jsonify({'success': True, 'message': 'Manual Jobs feed already exists'})
    
    # Create Manual Jobs feed
    default_keyword_prompt = "Extract 2 keywords from job description"
    default_proposal_prompt = "Generate proposal for job"
    default_olostep_prompt = "Find contact info for {search_target}"
    
    if is_postgres:
        c.execute("""INSERT INTO rss_feeds 
                    (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                    VALUES (%s, %s, %s, %s, %s)""",
                 ("Manual Jobs", "manual://jobs", default_keyword_prompt, 
                  default_proposal_prompt, default_olostep_prompt))
    else:
        c.execute("""INSERT INTO rss_feeds 
                    (name, url, keyword_prompt, proposal_prompt, olostep_prompt)
                    VALUES (?, ?, ?, ?, ?)""",
                 ("Manual Jobs", "manual://jobs", default_keyword_prompt, 
                  default_proposal_prompt, default_olostep_prompt))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Manual Jobs feed created'})

@app.route('/fix-job-sources', methods=['POST'])
def fix_job_sources():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Get RSS feed IDs
    if is_postgres:
        c.execute("SELECT id FROM rss_feeds WHERE name = %s", ('Web Development',))
        web_dev_result = c.fetchone()
        web_dev_id = web_dev_result[0] if web_dev_result else None
        
        c.execute("SELECT id FROM rss_feeds WHERE name = %s", ('Manual Jobs',))
        manual_result = c.fetchone()
        manual_id = manual_result[0] if manual_result else None
    else:
        c.execute("SELECT id FROM rss_feeds WHERE name = ?", ('Web Development',))
        web_dev_result = c.fetchone()
        web_dev_id = web_dev_result[0] if web_dev_result else None
        
        c.execute("SELECT id FROM rss_feeds WHERE name = ?", ('Manual Jobs',))
        manual_result = c.fetchone()
        manual_id = manual_result[0] if manual_result else None
    
    if not web_dev_id or not manual_id:
        conn.close()
        return jsonify({'success': False, 'error': 'RSS feeds not found'})
    
    # Update jobs based on URL patterns
    if is_postgres:
        # Jobs from vollna.com RSS should be Web Development
        c.execute("UPDATE jobs SET rss_source_id = %s WHERE rss_source_id IS NULL AND url LIKE '%vollna.com%'", (web_dev_id,))
        
        # Jobs from upwork.com should be Manual Jobs (Chrome extension)
        c.execute("UPDATE jobs SET rss_source_id = %s WHERE rss_source_id IS NULL AND url LIKE '%upwork.com%'", (manual_id,))
        
        # Any remaining NULL jobs go to Web Development (RSS feed jobs)
        c.execute("UPDATE jobs SET rss_source_id = %s WHERE rss_source_id IS NULL", (web_dev_id,))
    else:
        # Jobs from vollna.com RSS should be Web Development
        c.execute("UPDATE jobs SET rss_source_id = ? WHERE rss_source_id IS NULL AND url LIKE '%vollna.com%'", (web_dev_id,))
        
        # Jobs from upwork.com should be Manual Jobs (Chrome extension)
        c.execute("UPDATE jobs SET rss_source_id = ? WHERE rss_source_id IS NULL AND url LIKE '%upwork.com%'", (manual_id,))
        
        # Any remaining NULL jobs go to Web Development (RSS feed jobs)
        c.execute("UPDATE jobs SET rss_source_id = ? WHERE rss_source_id IS NULL", (web_dev_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Job sources fixed'})

@app.route('/debug-manual-jobs')
def debug_manual_jobs():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Get Manual Jobs RSS feed ID
    if is_postgres:
        c.execute("SELECT id FROM rss_feeds WHERE name = %s", ('Manual Jobs',))
    else:
        c.execute("SELECT id FROM rss_feeds WHERE name = ?", ('Manual Jobs',))
    manual_result = c.fetchone()
    
    if not manual_result:
        conn.close()
        return jsonify({'error': 'Manual Jobs RSS feed not found'})
    
    manual_id = manual_result[0]
    
    # Get all jobs in Manual Jobs
    if is_postgres:
        c.execute("SELECT id, title, url, rss_source_id FROM jobs WHERE rss_source_id = %s", (manual_id,))
        jobs = c.fetchall()
        
        # Get count of jobs with NULL rss_source_id
        c.execute("SELECT COUNT(*) FROM jobs WHERE rss_source_id IS NULL")
        null_count = c.fetchone()[0]
        
        # Get count by URL pattern
        c.execute("SELECT COUNT(*) FROM jobs WHERE url LIKE %s", ('%upwork.com%',))
        upwork_count = c.fetchone()[0]
    else:
        c.execute("SELECT id, title, url, rss_source_id FROM jobs WHERE rss_source_id = ?", (manual_id,))
        jobs = c.fetchall()
        
        # Get count of jobs with NULL rss_source_id
        c.execute("SELECT COUNT(*) FROM jobs WHERE rss_source_id IS NULL")
        null_count = c.fetchone()[0]
        
        # Get count by URL pattern
        c.execute("SELECT COUNT(*) FROM jobs WHERE url LIKE ?", ('%upwork.com%',))
        upwork_count = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'manual_jobs_rss_id': manual_id,
        'jobs_in_manual_feed': len(jobs),
        'jobs_with_null_rss_id': null_count,
        'upwork_jobs_total': upwork_count,
        'sample_jobs': jobs[:5]
    })

@app.route('/debug-enriched')
def debug_enriched():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Get all enriched jobs with all columns
    c.execute("SELECT * FROM jobs WHERE enriched = 1 LIMIT 1")
    sample_job = c.fetchone()
    
    # Get column names (PostgreSQL vs SQLite)
    if is_postgres:
        c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'jobs'")
        columns = [(row[0],) for row in c.fetchall()]  # Format like SQLite PRAGMA
    else:
        c.execute("PRAGMA table_info(jobs)")
        columns = c.fetchall()
    
    conn.close()
    
    return jsonify({
        'columns': columns,
        'sample_job': sample_job
    })

@app.route('/add-enriched-column')
def add_enriched_column():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    try:
        c.execute('ALTER TABLE jobs ADD COLUMN enriched_at TEXT')
        conn.commit()
        return jsonify({'success': True, 'message': 'enriched_at column added'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/debug-team')
def debug_team():
    conn = system.get_db_connection()
    c = conn.cursor()
    
    # Get total count
    c.execute("SELECT COUNT(*) FROM team_profiles")
    total_count = c.fetchone()[0]
    
    # Get all profiles
    c.execute("SELECT * FROM team_profiles ORDER BY name")
    all_profiles = c.fetchall()
    
    conn.close()
    
    return jsonify({
        'database_type': 'PostgreSQL' if os.getenv('DATABASE_URL') else 'SQLite',
        'database_url_exists': bool(os.getenv('DATABASE_URL')),
        'total_count': total_count,
        'profiles_shown': len(all_profiles),
        'sample_profiles': all_profiles[:5]  # First 5 for debugging
    })

@app.route('/import-csv-profiles')
def import_csv_profiles():
    import csv
    import io
    
    csv_data = '''names,titles,skills,description,Profile_URL
Sachin M.,Full Stack Developer | Senior .Net Developer,"MySQL, Web Application, CMS Framework, ASP.NET, .NET Framework, .NET Compact Framework, .NET Core","Strong experience in system analysis, architecture, development, object-oriented design, system integration and leadership. Proficient with the Microsoft .NET Framework, PHP, Android, DynamicAX, PowerBI and SQL development.",https://www.upwork.com/freelancers/~015184bacbca7a5bfb/
Neha V.,Full Stack Web and Mobile App Development | AI Chatbot & Voice Agent,"AI Chatbot, Artificial Intelligence, Python, Full-Stack Development, ChatGPT, Web Application, Mobile App, AI Agent Development, OpenAPI, ChatGPT API Integration, Mobile App Development, Web Application Development, React Native, React, Node.js","Full stack developer with 5+ years of experience building modern web and mobile applications, as well as integrating AI-driven chatbots and voice agents into business workflows.",https://www.upwork.com/freelancers/~016a3078041587aff0/
Shobhit S.,Full Stack Developer | PHP | Angular | .NET |,"PHP, API Integration, Web Development, JavaScript, Mobile App Design, Mobile App, ASP.NET, .NET Framework, .NET Core, Angular, PHP Script","5+ years of experience in Web app development, creating apps, bug fixing existing apps and collaborating on major projects.",https://www.upwork.com/freelancers/~014d96f12f06a545bb/
Aditya S.,Mobile App Developer | React Native | Flutter | React Native Expo,"Hybrid App Development, Firebase Realtime Database, Firebase, React, React Native, API, ChatGPT, Google Maps API, Responsive Design, FinTech, Flutter, Mobile App Development, Android, iOS, NFC","Top Rated Plus Mobile App Developer with 7+ years of experience in mobile app development, specializing in Healthcare & Fintech applications.",https://www.upwork.com/freelancers/~016487ec9f3aab93c4/
Tahir S.,Mobile App Developer | iOS | Android,"Node.js, PostgreSQL, MySQL, Database, Web Development, NodeJS Framework, React, Redux, Web Application Development, Web Application, Angular, ChatGPT","Mobile Developer with 5+ years experience in Mobile Development with Swift, SwiftUI, Java/Kotlin, React Native and Flutter.",https://www.upwork.com/freelancers/~01ca241aae4f03b625/
Adnan K.,"Automation Expert | Zapier, Make.com, n8n","Zapier, Automation, Make.com, n8n, CRM Automation, Task Automation, System Automation","Certified specialist in Zapier, Make.com, and a variety of CRMs with over 5+ years of experience as a senior software engineer.",https://www.upwork.com/freelancers/~01635ad8021d6f9378/
Vishakha S.,Full Stack / AI-ML expert/ Python/ OpenCV/ ChatGPT/ OpenAI,"API Integration, Python, Web Development, PHP Script, Web Design, API, Artificial Intelligence, Machine Learning, TensorFlow, Golang, Full-Stack Development","Python developer and Data Scientist with 3+ years experience in Artificial intelligence, Machine learning and Deep learning.",https://www.upwork.com/freelancers/~018df5a16e04c63804/
Anurag K.,Full Stack Mobile App Developer | UI/UX Design | Hybrid App Dev.,"Hybrid App Development, React Native, React, iOS Development,Android App Development, Flutter, Payment Functionality, API Integration, Responsive Design, Front-End Development, Expo.io, Database, API","Full Stack Mobile App Developer with 4+ years of experience turning ideas into high-performing mobile applications.",https://www.upwork.com/freelancers/~0131ec49a5a4bbad75/
Vedika P.,WordPress | WooCommerce | Themes & Plugins Development,"API Integration, Responsive Design, WordPress, WooCommerce, WordPress Theme, WordPress Plugin, WordPress Website, WordPress e-Commerce, WordPress SEO Plugin, WordPress Development","WordPress and WooCommerce expert with over 4 years of experience helping businesses create and grow their online marketplaces.",https://www.upwork.com/freelancers/~011e78b81a5d7fbd59/
Manmeet S.,Facebook Certified Ads Specialist | SEO Specialist | Instagram Ads,"Facebook Ads Manager, Facebook Ad Campaign, Facebook Advertising, Digital Marketing, Social Media Advertising, Google Ads, SEO Plugin, Search Engine Optimization","Certified Facebook Ads expert, Google Ads Specialist, and Digital Marketing strategist with proven track record of 5x-8x growth.",https://www.upwork.com/freelancers/~0185aeba872197bac6/
Charu V.,Mobile App developer | React Native | Flutter,"React, Web Application Development, MERN Stack, NodeJS Framework, API Integration, Custom Web Design, MongoDB, AngularJS, Next.js","Experienced Web and Mobile Applications Developer with over 5 years of expertise in JavaScript, React Native, React.js, Node.js, Typescript development.",https://www.upwork.com/freelancers/~013ae3370ecc758581/
Aishwarya J.,"Native iOS & Android Developer, Swift | Kotlin, 8+ Years of Experience","Smartphone, MySQL, Objective-C, In-App Advertising, Map Integration, SQLite, In-App Purchases, Social Media Account Integration, iOS Developmen, HealthKit, iOS, Apple Xcode","Expert Native iOS & Android Developer with 8+ years experience in Mobile Development with Swift, Java/Kotlin.",https://www.upwork.com/freelancers/~0192672bf8a1b97c6a/
Anjali P.,Mobile Development | Flutter | Flutter Flow | React | React Native,"Android, Mobile App Development,React Native,Hybrid App Development, Google Maps API, Location-Based Service, Flutter, FlutterFlow, Dart, Expo.io, iOS, Health & Fitness","React Native Developer with 5+ Years of Experience specializing in React Native for building high-performance cross-platform apps.",https://www.upwork.com/freelancers/~0176e02408e1ac4f53/
Arnika G.,Senior .Net Developer / Project Manager/,"Project Management, Agile Project Management, Jira, ASP.NET, C#, ASP","Passionate .NET developer with 7 years of expertise in ASP.NET Core MVC, Web API, and Angular.",https://www.upwork.com/freelancers/~015cfd4b0eb129f62c/
Balkrishna P.,Full Stack Developer | .Net | Web and Mobile App,"Google Maps, Mobile App, React Native, Mobile App Development, iOS, Android","Dedicated .NET developer with 5 years of expertise in ASP.NET Core MVC, Web API, and Angular.",https://www.upwork.com/freelancers/~0123bc1adae484eb4b/
Mahendra S.,"Senior iOS Developer, Swift, SwiftUI, Objective-C","Objective-C, Swift, Firebase, iOS, RxSwift, MVC Framework, Health & Fitness, NFC, Ecommerce, GPS","Native Mobile Developer with 8+ years experience in Mobile Development with Swift.",https://www.upwork.com/freelancers/~01ea171d836a42fa73/
Yashdeep M.,QA Tester / QA Engineer,"Test Results & Analysis, Static Testing, Alpha Testing, Quality Assurance, Testing, Software Testing, Software QA","Manual black-box testing, functional, non-functional testing expert with QA methodologies knowledge.",https://www.upwork.com/freelancers/~01b76d2ff092e170ad/
Abhish B.,Native iOS & Android Developer | Swift | Kotlin|8+ Years of Experience,"MySQL, Firebase, User Authentication, Social Media Account Integration, watchOS, Mobile App Development, Swift, iOS, Wearables Software, Wear OS, Machine Learning","Expert Native iOS & Android Developer with 8+ years experience in Mobile Development with Swift, Java/Kotlin.",https://www.upwork.com/freelancers/~01886764e7d248e2db/
Shreya D.,"Full-Stack | Replit, Bubble, Lovable, Cursor, Bolt.new, Famous.ai","API Development, CMS Development, Replit, Low-Code Development, No-Code Development, No-Code Website, No-Code Landing Page, Bubble.io, MERN Stack, Full-Stack Development, Mobile App Development, Android App Development, iOS Development","Full-stack developer with 7+ years of experience, specializing in the MERN stack and modern low-code/no-code tools.",https://www.upwork.com/freelancers/~017af652fec3c91123/
Harshit J.,"Senior iOS, Swift, SwiftUI, Objective-C","Automation, Zapier, Make.com, n8n, CRM Automation, Twilio, Task Automation","Native Mobile Developer with 8+ years experience in Mobile Development with Swift.",https://www.upwork.com/freelancers/~01d35319ad4870ddfa/
Sanjivani R.,"Full Stack & AI/ML Developer | GPT, Python, Node.js, Angular | ChatBot","GPT-4o, Python, AI Chatbot, AI Agent Development, React, Node.js, AI Development, Chatbot Development, Machine Learning, Full-Stack Development, Web Development, FastAPI, API","Full Stack Developer & AI Engineer with 6+ years of experience in building web applications, AI systems, and chatbots.",https://www.upwork.com/freelancers/~0106c672134f97d75d/
Shreya S.,iOS Android Flutter Flutter Flow | Full Stack Mobile App Development,"Java, Kotlin, Android Studio, XML, Git,  Version control","Highly skilled Android developer with 6 years of experience building robust and user-friendly applications.",https://www.upwork.com/freelancers/~01c9aa521264975eba/
Anurag N.,"Web, Mobile, API Test Engineer | Automation Specialist | 7+ Years Exp.","User Acceptance Testing, Manual Testing, Mobile App Testing, Web Testing, Test Case Design, Bug Reports, Testing, Appium","Web/App/Mobile/Database quality test engineer with more than 7 years of experience.",https://www.upwork.com/freelancers/~01c50ab3e81349fe3c/
Leena M.,"UI/UX designer | Figma Expert | Healthcare | iOS, Android & Web","UI/UX Prototyping, Graphic Design, Figma, UX & UI, User Experience, Android, iOS","4+ years of rich experience in user interface (UI) and user experience (UX) design.",https://www.upwork.com/freelancers/~01b42dab1b19255c0e/
Deepak N.,"Senior iOS, Swift, SwiftUI, Objective C (Maps| Fintech| Fitness)","In-App Advertising, Map Integration, MySQL, Swift, Objective-C, Social Media Account Integration, iOS, iOS Development, Smartphone, SQLite, HealthKit, Kotlin","Native Mobile Developer with 8+ years experience in Mobile Development with Swift.",https://www.upwork.com/freelancers/~01e26cbadeb232e4f5/
Khushal K.,Back-end dev I Data Engineering | ETL/Web Scraper I Automation expert,"Microsoft Azure, Microsoft SQL Server, AWS Application, ETL, Database Security, Microsoft Power BI, Data Mining, Business Intelligence, Data Cleaning, Data Science, Data Analysis, Data Modeling, Automation, OAuth, Back-End Development","Highly skilled Full stack Developer with 6+ years of experience in developing and maintaining web applications.",https://www.upwork.com/freelancers/~01b2a08e4411b91379/
Shubham J.,"6 Years Experienced Android App Developer | Java, Kotlin, Sqlite","MySQL, In-App Advertising, In-App Purchases, User Authentication, iOS, Android, Smartphone, Map Integration, Model View ViewModel, Flutter, Hybrid App Development, FlutterFlow, Dart, Chat & Messaging Software, API Integration","Highly skilled Android developer with 6 years of experience building robust and user-friendly applications.",https://www.upwork.com/freelancers/~01a90d2fc0d6aa52fc/
Pavan R.,Senior iOS/Android Developer | Flutter | React Native | NFC | WatchOS,"Mobile App, NFC, Swift, Apple Xcode, iOS, Mobile App Development, Apple Watch Application, Bluetooth, iOS Development, Android, Payment Functionality, Flutter, Flutter Stack, FlutterFlow, watchOS","Having 5+yrs of experience in iOS and Android app development with Apple watch, watch OS, BLE and NFC Apps.",https://www.upwork.com/freelancers/~014dac5bcae89fb084/
Ravi K.,Top Rated Plus Full Stack Web Developer,"React, Node.js, JavaScript, MongoDB, ChatGPT, OpenAI API, Web Development, Angular, MERN Stack, Front-End Development, Back-End Development, Twilio, WebRTC, Framer","Top Rated Plus Upwork Freelancer with over 7+ years of hands-on involvement in the technology sector.",https://www.upwork.com/freelancers/~019692fcaaaaf56cb8/
Mohd Muaz S.,"NFC, IoT, BLE, Map, iBeacon, Android, iOS","Java, Swift, Android App Development, Kotlin, iOS, Android, iOS Development, API Integration, Smartphone, Camera, Smartwatch, Mobile App Development, NFC, Bluetooth LE, RFID","Expert full stack mobile Developer, having 5+ years experience with NFC, BLE, RFID development.",https://www.upwork.com/freelancers/~01b22b05d7992372e1/
Ankit C.,Full Stack / AI-ML expert/ Python/ OpenCV/ ChatGPT/ OpenAI,"Natural Language Processing, NLTK, OpenCV, Python, Microsoft Azure, React, MySQL, Node.js, SQLite, React Native,Firebase","Python developer and Data Scientist over 5+ years experience in Artificial intelligence, Machine learning and Deep learning.",https://www.upwork.com/freelancers/~015bc920be81604685/
Vivek V.,Full Stack | React | Node | Laravel | PHP | GIS | SaaS | WebRTC,"MongoDB, Node.js, React, PHP, Next.js, JavaScript, Laravel, Web Development, API Integration, In-App Subscription, Web Design, Angular, TypeScript, Web Application,WebRTC","Started software development 9 years ago which varies from Web and mobile Development to Network Management.",https://www.upwork.com/freelancers/~01b248f7f48547dd62/
Aditya T.,Mobile App Developer | React Native | Flutter | HealthTech Expert,"React Native, Flutter, Flutter Stack, Hybrid App Development, Mobile App Development, iOS Development, Android App Development, Expo.io, Health & Wellness, FinTech, Healthcare Software","Top Rated Plus Mobile App Developer with 7+ years of experience in Healthcare and Fintech applications.",https://www.upwork.com/freelancers/~01a28b6678a7d7bdc2/
Vivek S.,Full Stack Developer | ChatBot Development | AI ML | Mobile App,"API, PHP, SQL, PostgreSQL, MongoDB, MySQL, Laravel, CodeIgniter, PHP Script Core PHP, Web Application Development, API Integration","Full Stack Developer with over 8+ years of hands-on experience building high-performance web, mobile, and AI-driven applications.",https://www.upwork.com/freelancers/~0158d25f0bff48c968/
Suyog D.,"iOS, Android, Fintech, Watch, Fitness Expert & AI Expert","Android App Development, iOS Development, Kotlin, Wear OS, watchOS, iOS, Smartwatch, Swift, Apple Watch, Mobile App Development, Flutter, Apple HealthKit, FlutterFlow, React Native, AI Development","Native Mobile Developer with 8+ years experience in Mobile Development with Swift, SwiftUI, Java/Kotlin.",https://www.upwork.com/freelancers/~0186b48df52f6fcfb2/
Isha P.,Lead Generation | Email Marketing | Multi Channel Marketing,"HubSpot, Lead Generation, Campaign Management, Email Campaign Setup, Data Entry, Error Detection, Mailchimp, Social Media Advertising, ChatGPT, Email Marketing, Email Marketing Strategy","Expertise in Lead Generation, Email Marketing, Email Warmup, Domain Setup with 4 years of strong experience.",https://www.upwork.com/freelancers/~01e6d07365dc1f8658/
Karan K.,"UI/UX designer | Figma Expert | Healthcare | iOS, Android & Web","Figma, UI/UX Prototyping, Web Design, Adobe Photoshop, Mobile UI Design, Mobile App Design, Adobe Inc., Adobe InDesign, App Design, UI Graphics, Adobe Photoshop Elements, UX & UI, Design & Usability Research, GUI Design, Wireframing","5+ years of rich experience in user interface (UI) and user experience (UX) design.",https://www.upwork.com/freelancers/~017093b071d2707f12/
Suruchi G.,React native/ Android/ iOS/ Swift/Kotlin,"Payment Gateway Integration, Google Maps API, iOS Development, Mobile App Development, SQLite, Swift, Firebase, React Native, Kotlin, Salesforce, Android App Development, Location-Based Service","Full stack mobile app developer with over 5 years experience in IT Industry.",https://www.upwork.com/freelancers/~012a4fe4880bfb0872/
Ishan J.,Full stack developer / ReactJS/ AngularJS/ NodeJS,"Python, MySQL, MongoDB, TypeScript, AWS Application, MySQL Programming, React, Node.js, Salesforce CRM","Full stack web developer, with very vast experience in Machine learning and Software development of 5+ years.",https://www.upwork.com/freelancers/~01fa2dd4b42277fe84/
Saloni K.,Social Media marketing | | SEO | Lead Generation,"Search Engine Optimization, ChatGPT, Product Listings ,Email Support, Marketing, Order Fulfillment, Automation, 3D Product Rendering, Lead Generation, Photo Color Correction, Data Entry, 3D Image, Email Marketing, Email Campaign Setup","Specialist in Social Media Management, SEO, Lead Generation with expertise in Instagram, Facebook, LinkedIn marketing.",https://www.upwork.com/freelancers/~016a615b71eb97817d/
Devendra B.,"UI/UX designer | Figma Expert | iOS, Android & Web","UI/UX Prototyping, Figma, Design Concept, Design Enhancement, Web & Mobile Design Consultation, Mobile App, Custom Web Design, Web Design, Mobile App Design, iOS, Android, Design & Usability Research","4+ years of rich experience in user interface (UI) and user experience (UX) design.",https://www.upwork.com/freelancers/~01b29a0d940cc561da/
Richa N.,Mobile app developer,"React Native, Python, Native App Development, Java, Android, iOS, NodeJS Framework, Django, TensorFlow, NFC","Expert full stack mobile Developer, having 5+ years experience with NFC, BLE development.",https://www.upwork.com/freelancers/~010a55f29d5644ce7b/
Rohit M.,Mobile App Developer | iOS | Android | WatchOS | Apple watch,"API Integration, Swift, Mobile App Development, Firebase, Chat & Messaging Software, Mobile App, Location-Based Service, Flutter, React Native, Kotlin, Mobile App Design","6+ years of experience in iOS mobile app development, creating Native apps, bug fixing existing apps.",https://www.upwork.com/freelancers/~015fb47072480c3f60/
Neha N.,"React, React Native, Flutter & Nodejs Developer | 6+ Years | AI Expert","React Native, React, Node.js, AI Platform, JavaScript, TypeScript, Amazon Web Services, ExpressJS, GraphQL, Next.js, Map Integration, Expo.io, MongoDB, Flutter, FlutterFlow","Full-stack developer passionate about creating exceptional digital and AI-powered solutions with 6+ years experience.",https://www.upwork.com/freelancers/~0178d79e42e2a4e8c0/'''
    
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        # Clear existing profiles first
        c.execute("DELETE FROM team_profiles")
        
        # Parse CSV
        csv_reader = csv.DictReader(io.StringIO(csv_data))
        imported_count = 0
        
        for row in csv_reader:
            if row['names'].strip():  # Skip empty rows
                # Extract experience years from description (rough estimate)
                description = row['description']
                experience_years = 5  # default
                if '3+' in description or '3 years' in description:
                    experience_years = 3
                elif '4+' in description or '4 years' in description:
                    experience_years = 4
                elif '5+' in description or '5 years' in description:
                    experience_years = 5
                elif '6+' in description or '6 years' in description:
                    experience_years = 6
                elif '7+' in description or '7 years' in description:
                    experience_years = 7
                elif '8+' in description or '8 years' in description:
                    experience_years = 8
                elif '9+' in description or '9 years' in description:
                    experience_years = 9
                
                # Determine hourly rate based on experience
                if experience_years <= 3:
                    hourly_rate = '$20-35/hr'
                elif experience_years <= 5:
                    hourly_rate = '$25-45/hr'
                elif experience_years <= 7:
                    hourly_rate = '$30-55/hr'
                else:
                    hourly_rate = '$35-65/hr'
                
                # Determine specialization from title
                title = row['titles']
                if 'iOS' in title or 'Swift' in title:
                    specialization = 'iOS Development'
                elif 'Android' in title or 'Kotlin' in title:
                    specialization = 'Android Development'
                elif 'React Native' in title or 'Flutter' in title:
                    specialization = 'Cross-Platform Mobile'
                elif 'AI' in title or 'ML' in title or 'ChatGPT' in title:
                    specialization = 'AI/ML Development'
                elif '.NET' in title or 'ASP.NET' in title:
                    specialization = '.NET Development'
                elif 'UI/UX' in title or 'Figma' in title:
                    specialization = 'UI/UX Design'
                elif 'QA' in title or 'Test' in title:
                    specialization = 'Quality Assurance'
                elif 'Marketing' in title or 'SEO' in title:
                    specialization = 'Digital Marketing'
                else:
                    specialization = 'Full Stack Development'
                
                if is_postgres:
                    c.execute("""INSERT INTO team_profiles 
                                (name, title, skills, description, profile_url, hourly_rate, experience_years, specialization, active)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                             (row['names'], row['titles'], row['skills'], row['description'][:500], 
                              row['Profile_URL'], hourly_rate, experience_years, specialization, 1))
                else:
                    c.execute("""INSERT INTO team_profiles 
                                (name, title, skills, description, profile_url, hourly_rate, experience_years, specialization, active)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (row['names'], row['titles'], row['skills'], row['description'][:500], 
                              row['Profile_URL'], hourly_rate, experience_years, specialization, 1))
                imported_count += 1
        
        # Get final count before closing
        c.execute("SELECT COUNT(*) FROM team_profiles")
        final_count = c.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully imported {imported_count} team profiles from CSV',
            'final_count_in_db': final_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/generate_outreach', methods=['POST'])
def generate_outreach():
    try:
        data = request.json
        outreach_type = data['type']
        prompt = data['prompt']
        job_title = data['job_title']
        job_description = data['job_description']
        
        if outreach_type == 'whatsapp':
            full_prompt = f"{prompt}\n\nJob Title: {job_title}\nJob Description: {job_description}\n\nGenerate a brief, friendly WhatsApp message:"
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": full_prompt}],
                max_tokens=250
            )
            message = response.choices[0].message.content.strip()
            return jsonify({'success': True, 'message': message})
            
        elif outreach_type == 'linkedin':
            full_prompt = f"{prompt}\n\nJob Title: {job_title}\nJob Description: {job_description}\n\nGenerate a professional LinkedIn message:"
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": full_prompt}],
                max_tokens=400
            )
            message = response.choices[0].message.content.strip()
            return jsonify({'success': True, 'message': message})
            
        elif outreach_type == 'email':
            subject = data.get('subject', '')
            followup_subject = data.get('followup_subject', '')
            
            # Generate initial email
            email_prompt = f"{prompt}\n\nJob Title: {job_title}\nJob Description: {job_description}\n\nGenerate a professional email body:"
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": email_prompt}],
                max_tokens=500
            )
            email_body = response.choices[0].message.content.strip()
            
            # Generate follow-up email
            followup_prompt = f"Generate a follow-up email body for this job if no response received to initial email:\n\nJob Title: {job_title}\nJob Description: {job_description}\n\nGenerate a polite follow-up email body:"
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": followup_prompt}],
                max_tokens=400
            )
            followup_body = response.choices[0].message.content.strip()
            
            return jsonify({
                'success': True,
                'subject': subject or f"Regarding: {job_title}",
                'body': email_body,
                'followup_subject': followup_subject or f"Follow-up: {job_title}",
                'followup_body': followup_body
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/fix-vollna-jobs', methods=['GET', 'POST'])
def fix_vollna_jobs():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Get RSS feed IDs
    if is_postgres:
        c.execute("SELECT id FROM rss_feeds WHERE name = %s", ('Web Development',))
        web_dev_result = c.fetchone()
        c.execute("SELECT id FROM rss_feeds WHERE name = %s", ('Manual Jobs',))
        manual_result = c.fetchone()
    else:
        c.execute("SELECT id FROM rss_feeds WHERE name = ?", ('Web Development',))
        web_dev_result = c.fetchone()
        c.execute("SELECT id FROM rss_feeds WHERE name = ?", ('Manual Jobs',))
        manual_result = c.fetchone()
    
    if not web_dev_result or not manual_result:
        conn.close()
        return jsonify({'success': False, 'error': 'RSS feeds not found'})
    
    web_dev_id = web_dev_result[0]
    manual_id = manual_result[0]
    
    # Move vollna.com jobs from Manual Jobs to Web Development
    if is_postgres:
        c.execute("UPDATE jobs SET rss_source_id = %s WHERE rss_source_id = %s AND url LIKE '%vollna.com%'", (web_dev_id, manual_id))
        moved_count = c.rowcount
    else:
        c.execute("UPDATE jobs SET rss_source_id = ? WHERE rss_source_id = ? AND url LIKE '%vollna.com%'", (web_dev_id, manual_id))
        moved_count = c.rowcount
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': f'Moved {moved_count} vollna.com jobs to Web Development'})

@app.route('/fix-web-dev-prompts', methods=['POST'])
def fix_web_dev_prompts():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    correct_keyword_prompt = """Extract 2 specific app search terms from this job description for Google Play Store searching.
Focus on the app's PURPOSE and USER NEED, not technical details.

AVOID these technical/generic terms:
- user-friendly interface, app design, app functionality, stable performance
- efficient operation, user experience, mobile application, engagement
- publishing, app development, full-stack development, mobile development
- android, web, react, react native, flutter

GOOD examples:
- For wellness app: "wellness tracker", "meditation apps"
- For AI health app: "health AI", "fitness assistant"
- For expense tracking: "expense manager", "budget tracker"
- For note taking: "note taking", "digital journal"

Job: {job_description}

Return exactly 2 specific search terms separated by comma:"""
    
    correct_proposal_prompt = """Generate a Proposalgenie-format proposal for this job:

Job Title: {job_title}
Job Description: {job_description}

Work Examples: {examples_text}

Follow the exact format:
- Start with: {greeting}
- Short intro with role + years + specialization
- Paragraph 1: technical fit + expected result
- Paragraph 2: Work examples (use the provided examples)
- Paragraph 3: exactly 2 thoughtful developer/designer questions
- Paragraph 4: CTA with call availability

Use Unicode formatting, no markdown. Be conversational but professional."""
    
    correct_olostep_prompt = """Find contact info for {search_target} in {city}, {country}. Get LinkedIn, email, phone, WhatsApp."""
    
    if is_postgres:
        c.execute("""UPDATE rss_feeds SET 
                     keyword_prompt = %s, proposal_prompt = %s, olostep_prompt = %s
                     WHERE name = %s""",
                 (correct_keyword_prompt, correct_proposal_prompt, correct_olostep_prompt, 'Web Development'))
    else:
        c.execute("""UPDATE rss_feeds SET 
                     keyword_prompt = ?, proposal_prompt = ?, olostep_prompt = ?
                     WHERE name = ?""",
                 (correct_keyword_prompt, correct_proposal_prompt, correct_olostep_prompt, 'Web Development'))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Web Development prompts updated to correct version'})

# Start all active RSS feeds
system.start_all_active_feeds()

@app.route('/analytics')
@login_required
def analytics():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Monthly enrichment stats
    if is_postgres:
        c.execute("""
            SELECT 
                DATE_TRUNC('month', CAST(posted_date AS DATE)) as month,
                enriched_by,
                COUNT(*) as count
            FROM jobs 
            WHERE enriched = 1 AND enriched_by IS NOT NULL
            GROUP BY DATE_TRUNC('month', CAST(posted_date AS DATE)), enriched_by
            ORDER BY month DESC, enriched_by
        """)
    else:
        c.execute("""
            SELECT 
                strftime('%Y-%m', posted_date) as month,
                enriched_by,
                COUNT(*) as count
            FROM jobs 
            WHERE enriched = 1 AND enriched_by IS NOT NULL
            GROUP BY strftime('%Y-%m', posted_date), enriched_by
            ORDER BY month DESC, enriched_by
        """)
    enrichment_stats = c.fetchall()
    
    # Monthly proposal submission stats
    if is_postgres:
        c.execute("""
            SELECT 
                DATE_TRUNC('month', CAST(posted_date AS DATE)) as month,
                submitted_by,
                proposal_status,
                COUNT(*) as count
            FROM jobs 
            WHERE submitted_by IS NOT NULL AND proposal_status != 'Not Submitted'
            GROUP BY DATE_TRUNC('month', CAST(posted_date AS DATE)), submitted_by, proposal_status
            ORDER BY month DESC, submitted_by, proposal_status
        """)
    else:
        c.execute("""
            SELECT 
                strftime('%Y-%m', posted_date) as month,
                submitted_by,
                proposal_status,
                COUNT(*) as count
            FROM jobs 
            WHERE submitted_by IS NOT NULL AND proposal_status != 'Not Submitted'
            GROUP BY strftime('%Y-%m', posted_date), submitted_by, proposal_status
            ORDER BY month DESC, submitted_by, proposal_status
        """)
    proposal_stats = c.fetchall()
    
    conn.close()
    return render_template('analytics.html', enrichment_stats=enrichment_stats, proposal_stats=proposal_stats)

@app.route('/check-db-type')
def check_db_type():
    return jsonify({
        'database_url_exists': bool(os.getenv('DATABASE_URL')),
        'database_url': os.getenv('DATABASE_URL', 'Not set')[:50] + '...' if os.getenv('DATABASE_URL') else 'Not set',
        'using_postgres': bool(os.getenv('DATABASE_URL'))
    })

@app.route('/fix-null-statuses', methods=['POST'])
def fix_null_statuses():
    """Set default values for NULL status fields"""
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        if is_postgres:
            c.execute("""
                UPDATE jobs 
                SET proposal_status = 'Not Submitted' 
                WHERE proposal_status IS NULL
            """)
            rows1 = c.rowcount
            
            c.execute("""
                UPDATE jobs 
                SET outreach_status = 'Pending' 
                WHERE outreach_status IS NULL
            """)
            rows2 = c.rowcount
            
            c.execute("""
                UPDATE jobs 
                SET submitted_by = '' 
                WHERE submitted_by IS NULL
            """)
            rows3 = c.rowcount
        else:
            c.execute("""
                UPDATE jobs 
                SET proposal_status = 'Not Submitted' 
                WHERE proposal_status IS NULL
            """)
            rows1 = c.rowcount
            
            c.execute("""
                UPDATE jobs 
                SET outreach_status = 'Pending' 
                WHERE outreach_status IS NULL
            """)
            rows2 = c.rowcount
            
            c.execute("""
                UPDATE jobs 
                SET submitted_by = '' 
                WHERE submitted_by IS NULL
            """)
            rows3 = c.rowcount
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'proposal_status_fixed': rows1,
            'outreach_status_fixed': rows2,
            'submitted_by_fixed': rows3,
            'total_fixed': rows1 + rows2 + rows3
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/test-job-data/<job_id>')
def test_job_data(job_id):
    """Test endpoint to see actual job data"""
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    if is_postgres:
        c.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
    else:
        c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    
    job = c.fetchone()
    
    if not job:
        conn.close()
        return jsonify({'error': 'Job not found'})
    
    # Get column names
    if is_postgres:
        c.execute("""
            SELECT column_name, ordinal_position 
            FROM information_schema.columns 
            WHERE table_name = 'jobs' 
            ORDER BY ordinal_position
        """)
        columns = [col[0] for col in c.fetchall()]
    else:
        c.execute("PRAGMA table_info(jobs)")
        columns = [col[1] for col in c.fetchall()]
    
    conn.close()
    
    # Create a dict of column:value
    job_dict = {}
    for i, col_name in enumerate(columns):
        if i < len(job):
            job_dict[f"{i}_{col_name}"] = job[i]
    
    return jsonify({
        'job_id': job_id,
        'total_columns': len(columns),
        'job_data_length': len(job),
        'data': job_dict,
        'status_fields': {
            'proposal_status': job[25] if len(job) > 25 else 'INDEX OUT OF RANGE',
            'submitted_by': job[26] if len(job) > 26 else 'INDEX OUT OF RANGE',
            'outreach_status': job[24] if len(job) > 24 else 'INDEX OUT OF RANGE'
        }
    })

@app.route('/debug-columns')
def debug_columns():
    conn = system.get_db_connection()
    c = conn.cursor()
    is_postgres = os.getenv('DATABASE_URL') is not None
    
    # Get column names
    if is_postgres:
        c.execute("""
            SELECT column_name, ordinal_position, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'jobs' 
            ORDER BY ordinal_position
        """)
        columns = c.fetchall()
        column_list = [{'name': col[0], 'position': col[1], 'type': col[2]} for col in columns]
    else:
        c.execute("PRAGMA table_info(jobs)")
        columns = c.fetchall()
        column_list = [{'name': col[1], 'position': col[0], 'type': col[2]} for col in columns]
    
    # Get a sample job
    c.execute("SELECT * FROM jobs LIMIT 1")
    sample_job = c.fetchone()
    
    conn.close()
    
    return jsonify({
        'database_type': 'PostgreSQL' if is_postgres else 'SQLite',
        'columns': column_list,
        'sample_job_length': len(sample_job) if sample_job else 0,
        'column_count': len(column_list)
    })

@app.route('/add-status-columns', methods=['POST'])
def add_status_columns():
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        columns_to_add = [
            ('outreach_status', 'TEXT DEFAULT \'Pending\''),
            ('proposal_status', 'TEXT DEFAULT \'Not Submitted\''),
            ('submitted_by', 'TEXT'),
            ('enriched_at', 'TEXT'),
            ('enriched_by', 'TEXT')
        ]
        
        added_columns = []
        existing_columns = []
        
        for col_name, col_type in columns_to_add:
            try:
                if is_postgres:
                    c.execute(f'ALTER TABLE jobs ADD COLUMN {col_name} {col_type}')
                else:
                    c.execute(f'ALTER TABLE jobs ADD COLUMN {col_name} {col_type}')
                conn.commit()
                added_columns.append(col_name)
            except Exception as e:
                conn.rollback()
                existing_columns.append(col_name)
        
        conn.close()
        
        return jsonify({
            'success': True,
            'added': added_columns,
            'existing': existing_columns,
            'message': f'Added {len(added_columns)} columns, {len(existing_columns)} already existed'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/fix-missing-columns', methods=['GET', 'POST'])
def fix_missing_columns():
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        is_postgres = os.getenv('DATABASE_URL') is not None
        
        if is_postgres:
            # Add columns to PostgreSQL
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN proposal_status TEXT DEFAULT \'Not Submitted\'')
                conn.commit()
            except Exception as e:
                if 'already exists' not in str(e):
                    conn.rollback()
                    
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN submitted_by TEXT')
                conn.commit()
            except Exception as e:
                if 'already exists' not in str(e):
                    conn.rollback()
                    
            try:
                c.execute('ALTER TABLE jobs ADD COLUMN enriched_by TEXT')
                conn.commit()
            except Exception as e:
                if 'already exists' not in str(e):
                    conn.rollback()
        
        conn.close()
        return jsonify({'success': True, 'message': 'Status columns added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Add missing columns on startup for PostgreSQL
if os.getenv('DATABASE_URL'):
    try:
        conn = system.get_db_connection()
        c = conn.cursor()
        
        # Add missing columns if they don't exist
        columns_to_add = [
            ('proposal_status', 'TEXT DEFAULT \'Not Submitted\''),
            ('submitted_by', 'TEXT'),
            ('enriched_by', 'TEXT')
        ]
        
        for column_name, column_def in columns_to_add:
            try:
                c.execute(f'ALTER TABLE jobs ADD COLUMN {column_name} {column_def}')
                conn.commit()
                print(f"Added column {column_name} to jobs table")
            except Exception as e:
                if 'already exists' not in str(e).lower():
                    print(f"Error adding column {column_name}: {e}")
                conn.rollback()
        
        conn.close()
    except Exception as e:
        print(f"Error adding columns: {e}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)