import sys
import sqlite3
from datetime import datetime, timedelta
import json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QProgressBar, 
                             QTabWidget, QSpinBox, QLineEdit, QTextEdit, 
                             QGridLayout, QFrame, QScrollArea, QComboBox,
                             QDialog, QDialogButtonBox, QFormLayout, QCheckBox)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QPixmap, QPainter, QPen, QColor, QIcon
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import seaborn as sns
import numpy as np
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect('pomodoro_data.db')
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Pomodoro sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                session_type TEXT NOT NULL,
                duration INTEGER NOT NULL,
                completed INTEGER NOT NULL,
                task_name TEXT,
                notes TEXT
            )
        ''')
        
        # User settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_duration INTEGER DEFAULT 25,
                short_break INTEGER DEFAULT 5,
                long_break INTEGER DEFAULT 15,
                long_break_interval INTEGER DEFAULT 4,
                auto_start_breaks INTEGER DEFAULT 0,
                auto_start_work INTEGER DEFAULT 0,
                sound_enabled INTEGER DEFAULT 1,
                username TEXT DEFAULT 'Kullanıcı'
            )
        ''')
        
        # Check if settings exist, if not create default
        cursor.execute('SELECT COUNT(*) FROM settings')
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO settings 
                (work_duration, short_break, long_break, long_break_interval, 
                 auto_start_breaks, auto_start_work, sound_enabled, username)
                VALUES (25, 5, 15, 4, 0, 0, 1, 'Kullanıcı')
            ''')
        
        self.conn.commit()
    
    def add_session(self, session_type, duration, completed, task_name="", notes=""):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (date, session_type, duration, completed, task_name, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), session_type, duration, completed, task_name, notes))
        self.conn.commit()
    
    def get_sessions(self, days=30):
        cursor = self.conn.cursor()
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute('''
            SELECT * FROM sessions 
            WHERE date >= ? 
            ORDER BY date DESC
        ''', (date_limit,))
        return cursor.fetchall()
    
    def get_settings(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM settings ORDER BY id DESC LIMIT 1')
        return cursor.fetchone()
    
    def update_settings(self, **kwargs):
        cursor = self.conn.cursor()
        # Get current settings
        current = self.get_settings()
        if current:
            # Update existing settings
            for key, value in kwargs.items():
                cursor.execute(f'UPDATE settings SET {key} = ? WHERE id = ?', (value, current[0]))
        self.conn.commit()
    
    def get_daily_stats(self, days=7):
        cursor = self.conn.cursor()
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute('''
            SELECT date(date) as day, 
                   COUNT(*) as total_sessions,
                   SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed_sessions,
                   SUM(CASE WHEN session_type = 'work' AND completed = 1 THEN duration ELSE 0 END) as work_minutes
            FROM sessions 
            WHERE date >= ? 
            GROUP BY date(date)
            ORDER BY day
        ''', (date_limit,))
        return cursor.fetchall()

class TimerThread(QThread):
    time_updated = pyqtSignal(int)
    timer_finished = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.duration = 0
        self.remaining = 0
        self.is_running = False
        self.is_paused = False
        
    def run(self):
        while self.is_running:
            if not self.is_paused:
                self.time_updated.emit(self.remaining)
                if self.remaining <= 0:
                    self.is_running = False
                    self.timer_finished.emit()
                    break
                self.remaining -= 1
            self.msleep(1000)  # Sleep for 1 second
    
    def start_timer(self, duration):
        self.duration = duration
        self.remaining = duration
        self.is_running = True
        self.is_paused = False
        if not self.isRunning():
            self.start()
    
    def pause_timer(self):
        self.is_paused = True
    
    def resume_timer(self):
        self.is_paused = False
    
    def stop_timer(self):
        self.is_running = False
        self.is_paused = False
        self.remaining = 0
        if self.isRunning():
            self.quit()
            self.wait()

class CircularProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.progress = 0
        self.total = 100
        
    def set_progress(self, current, total):
        self.progress = current
        self.total = total
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background circle
        painter.setPen(QPen(QColor(240, 240, 240), 8))
        painter.drawEllipse(20, 20, self.width()-40, self.height()-40)
        
        # Progress arc
        if self.total > 0:
            progress_angle = int(360 * (self.total - self.progress) / self.total)
            painter.setPen(QPen(QColor(67, 160, 71), 8))
            painter.drawArc(20, 20, self.width()-40, self.height()-40, 90*16, -progress_angle*16)

class StatisticsWidget(QWidget):
    def __init__(self, db_manager):
        super().__init__()
        self.db_manager = db_manager
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(12, 8))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        
        # Refresh button
        refresh_btn = QPushButton("İstatistikleri Yenile")
        refresh_btn.clicked.connect(self.update_charts)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        layout.addWidget(refresh_btn)
        
        self.setLayout(layout)
        self.update_charts()
    
    def update_charts(self):
        self.figure.clear()
        
        # Get data
        sessions = self.db_manager.get_sessions(30)
        daily_stats = self.db_manager.get_daily_stats(7)
        
        # Create subplots
        gs = self.figure.add_gridspec(2, 2, height_ratios=[1, 1], width_ratios=[1, 1])
        
        # 1. Daily productivity chart
        ax1 = self.figure.add_subplot(gs[0, 0])
        if daily_stats:
            dates = [stat[0] for stat in daily_stats]
            work_minutes = [stat[3] for stat in daily_stats]
            
            ax1.bar(dates, work_minutes, color='#4CAF50', alpha=0.7)
            ax1.set_title('Günlük Çalışma Süreleri (Dakika)', fontsize=12, fontweight='bold')
            ax1.set_xlabel('Tarih')
            ax1.set_ylabel('Dakika')
            ax1.tick_params(axis='x', rotation=45)
        
        # 2. Session completion rate
        ax2 = self.figure.add_subplot(gs[0, 1])
        if sessions:
            completed = len([s for s in sessions if s[4] == 1])
            total = len(sessions)
            incomplete = total - completed
            
            labels = ['Tamamlanan', 'Yarıda Kalan']
            sizes = [completed, incomplete]
            colors = ['#4CAF50', '#f44336']
            
            ax2.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
            ax2.set_title('Oturum Tamamlanma Oranı', fontsize=12, fontweight='bold')
        
        # 3. Weekly trend
        ax3 = self.figure.add_subplot(gs[1, 0])
        if daily_stats:
            dates = [stat[0] for stat in daily_stats]
            completed_sessions = [stat[2] for stat in daily_stats]
            
            ax3.plot(dates, completed_sessions, marker='o', color='#2196F3', linewidth=2, markersize=6)
            ax3.set_title('Haftalık Tamamlanan Oturum Trendi', fontsize=12, fontweight='bold')
            ax3.set_xlabel('Tarih')
            ax3.set_ylabel('Tamamlanan Oturum')
            ax3.tick_params(axis='x', rotation=45)
            ax3.grid(True, alpha=0.3)
        
        # 4. Session type distribution
        ax4 = self.figure.add_subplot(gs[1, 1])
        if sessions:
            session_types = {}
            for session in sessions:
                session_type = session[2]
                if session_type not in session_types:
                    session_types[session_type] = 0
                session_types[session_type] += 1
            
            labels = list(session_types.keys())
            sizes = list(session_types.values())
            colors = ['#FF9800', '#2196F3', '#9C27B0']
            
            ax4.bar(labels, sizes, color=colors[:len(labels)])
            ax4.set_title('Oturum Türü Dağılımı', fontsize=12, fontweight='bold')
            ax4.set_xlabel('Oturum Türü')
            ax4.set_ylabel('Adet')
        
        self.figure.tight_layout()
        self.canvas.draw()

class SettingsDialog(QDialog):
    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("Ayarlar")
        self.setModal(True)
        self.setMinimumSize(400, 300)
        self.init_ui()
        self.load_settings()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Form layout
        form_layout = QFormLayout()
        
        # User name
        self.username_edit = QLineEdit()
        form_layout.addRow("Kullanıcı Adı:", self.username_edit)
        
        # Timer durations
        self.work_spin = QSpinBox()
        self.work_spin.setMinimum(1)
        self.work_spin.setMaximum(60)
        self.work_spin.setSuffix(" dakika")
        form_layout.addRow("Çalışma Süresi:", self.work_spin)
        
        self.short_break_spin = QSpinBox()
        self.short_break_spin.setMinimum(1)
        self.short_break_spin.setMaximum(30)
        self.short_break_spin.setSuffix(" dakika")
        form_layout.addRow("Kısa Mola:", self.short_break_spin)
        
        self.long_break_spin = QSpinBox()
        self.long_break_spin.setMinimum(1)
        self.long_break_spin.setMaximum(60)
        self.long_break_spin.setSuffix(" dakika")
        form_layout.addRow("Uzun Mola:", self.long_break_spin)
        
        self.long_break_interval_spin = QSpinBox()
        self.long_break_interval_spin.setMinimum(2)
        self.long_break_interval_spin.setMaximum(10)
        self.long_break_interval_spin.setSuffix(" oturum")
        form_layout.addRow("Uzun Mola Aralığı:", self.long_break_interval_spin)
        
        # Auto-start options
        self.auto_start_breaks_check = QCheckBox("Molaları otomatik başlat")
        form_layout.addRow(self.auto_start_breaks_check)
        
        self.auto_start_work_check = QCheckBox("Çalışmayı otomatik başlat")
        form_layout.addRow(self.auto_start_work_check)
        
        self.sound_enabled_check = QCheckBox("Ses bildirimleri")
        form_layout.addRow(self.sound_enabled_check)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.save_settings)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        
    def load_settings(self):
        settings = self.db_manager.get_settings()
        if settings:
            self.username_edit.setText(settings[8])
            self.work_spin.setValue(settings[1])
            self.short_break_spin.setValue(settings[2])
            self.long_break_spin.setValue(settings[3])
            self.long_break_interval_spin.setValue(settings[4])
            self.auto_start_breaks_check.setChecked(bool(settings[5]))
            self.auto_start_work_check.setChecked(bool(settings[6]))
            self.sound_enabled_check.setChecked(bool(settings[7]))
    
    def save_settings(self):
        self.db_manager.update_settings(
            username=self.username_edit.text(),
            work_duration=self.work_spin.value(),
            short_break=self.short_break_spin.value(),
            long_break=self.long_break_spin.value(),
            long_break_interval=self.long_break_interval_spin.value(),
            auto_start_breaks=int(self.auto_start_breaks_check.isChecked()),
            auto_start_work=int(self.auto_start_work_check.isChecked()),
            sound_enabled=int(self.sound_enabled_check.isChecked())
        )
        self.accept()

class PomodoroApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.timer_thread = TimerThread()
        self.timer_thread.time_updated.connect(self.update_timer_display)
        self.timer_thread.timer_finished.connect(self.timer_finished)
        
        self.current_session = 0
        self.session_type = "work"  # work, short_break, long_break
        self.is_running = False
        
        self.init_ui()
        self.load_settings()
        
    def init_ui(self):
        self.setWindowTitle("Modern Pomodoro Timer")
        self.setGeometry(100, 100, 1200, 800)
        
        # Apply modern styling
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QTabWidget::pane {
                border: 1px solid #ddd;
                background-color: white;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                border: 1px solid #ccc;
                padding: 12px 24px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #ddd;
            }
        """)
        
        # Central widget with tabs
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Tab widget
        self.tabs = QTabWidget()
        
        # Timer tab
        self.timer_tab = self.create_timer_tab()
        self.tabs.addTab(self.timer_tab, "🍅 Pomodoro")
        
        # Statistics tab
        self.stats_tab = StatisticsWidget(self.db_manager)
        self.tabs.addTab(self.stats_tab, "📊 İstatistikler")
        
        # Profile tab
        self.profile_tab = self.create_profile_tab()
        self.tabs.addTab(self.profile_tab, "👤 Profil")
        
        layout.addWidget(self.tabs)
        
        # Status bar
        self.status_label = QLabel("Hazır")
        self.statusBar().addWidget(self.status_label)
        
    def create_timer_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Header with user info
        header_layout = QHBoxLayout()
        
        self.user_label = QLabel("Merhaba, Kullanıcı!")
        self.user_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #333;
                padding: 10px;
            }
        """)
        header_layout.addWidget(self.user_label)
        
        header_layout.addStretch()
        
        # Settings button
        settings_btn = QPushButton("⚙️ Ayarlar")
        settings_btn.clicked.connect(self.open_settings)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        header_layout.addWidget(settings_btn)
        
        layout.addLayout(header_layout)
        
        # Timer section
        timer_layout = QVBoxLayout()
        
        # Session type label
        self.session_label = QLabel("Çalışma Oturumu")
        self.session_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.session_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #4CAF50;
                margin: 20px;
            }
        """)
        timer_layout.addWidget(self.session_label)
        
        # Circular progress bar
        self.progress_bar = CircularProgressBar()
        timer_layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Time display
        self.time_label = QLabel("25:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("""
            QLabel {
                font-size: 48px;
                font-weight: bold;
                color: #333;
                margin: 20px;
            }
        """)
        timer_layout.addWidget(self.time_label)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶️ Başlat")
        self.start_btn.clicked.connect(self.start_timer)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        button_layout.addWidget(self.start_btn)
        
        self.pause_btn = QPushButton("⏸️ Duraklat")
        self.pause_btn.clicked.connect(self.pause_timer)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        button_layout.addWidget(self.pause_btn)
        
        self.reset_btn = QPushButton("🔄 Sıfırla")
        self.reset_btn.clicked.connect(self.reset_timer)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        button_layout.addWidget(self.reset_btn)
        
        timer_layout.addLayout(button_layout)
        
        # Task input
        task_layout = QVBoxLayout()
        
        task_label = QLabel("Görev:")
        task_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        task_layout.addWidget(task_label)
        
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Üzerinde çalışacağınız görevi girin...")
        self.task_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 2px solid #ddd;
                border-radius: 5px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
        """)
        task_layout.addWidget(self.task_input)
        
        # Session counter
        self.session_counter = QLabel("Oturum: 0/4")
        self.session_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.session_counter.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #666;
                margin: 10px;
            }
        """)
        task_layout.addWidget(self.session_counter)
        
        layout.addLayout(timer_layout)
        layout.addLayout(task_layout)
        
        return widget
        
    def create_profile_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Profile header
        profile_header = QLabel("Kullanıcı Profili")
        profile_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        profile_header.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #333;
                margin: 20px;
            }
        """)
        layout.addWidget(profile_header)
        
        # Profile stats
        stats_layout = QGridLayout()
        
        # Total sessions
        self.total_sessions_label = QLabel("Toplam Oturum\n0")
        self.total_sessions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_sessions_label.setStyleSheet("""
            QLabel {
                background-color: #4CAF50;
                color: white;
                padding: 20px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        stats_layout.addWidget(self.total_sessions_label, 0, 0)
        
        # Completed sessions
        self.completed_sessions_label = QLabel("Tamamlanan\n0")
        self.completed_sessions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.completed_sessions_label.setStyleSheet("""
            QLabel {
                background-color: #2196F3;
                color: white;
                padding: 20px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        stats_layout.addWidget(self.completed_sessions_label, 0, 1)
        
        # Total work time
        self.total_work_time_label = QLabel("Toplam Çalışma\n0 dakika")
        self.total_work_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_work_time_label.setStyleSheet("""
            QLabel {
                background-color: #FF9800;
                color: white;
                padding: 20px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        stats_layout.addWidget(self.total_work_time_label, 1, 0)
        
        # Success rate
        self.success_rate_label = QLabel("Başarı Oranı\n0%")
        self.success_rate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.success_rate_label.setStyleSheet("""
            QLabel {
                background-color: #9C27B0;
                color: white;
                padding: 20px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        stats_layout.addWidget(self.success_rate_label, 1, 1)
        
        layout.addLayout(stats_layout)
        
        # Recent sessions
        recent_label = QLabel("Son Oturumlar")
        recent_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #333;
                margin: 20px 0 10px 0;
            }
        """)
        layout.addWidget(recent_label)
        
        self.recent_sessions = QTextEdit()
        self.recent_sessions.setReadOnly(True)
        self.recent_sessions.setMaximumHeight(200)
        self.recent_sessions.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                background-color: #f9f9f9;
            }
        """)
        layout.addWidget(self.recent_sessions)
        
        layout.addStretch()
        
        return widget
        
    def load_settings(self):
        settings = self.db_manager.get_settings()
        if settings:
            self.work_duration = settings[1]
            self.short_break_duration = settings[2]
            self.long_break_duration = settings[3]
            self.long_break_interval = settings[4]
            self.auto_start_breaks = bool(settings[5])
            self.auto_start_work = bool(settings[6])
            self.sound_enabled = bool(settings[7])
            username = settings[8]
            
            self.user_label.setText(f"Merhaba, {username}!")
            self.update_timer_display(self.work_duration * 60)
            
        self.update_profile_stats()
        
    def update_profile_stats(self):
        sessions = self.db_manager.get_sessions(30)
        
        total_sessions = len(sessions)
        completed_sessions = len([s for s in sessions if s[4] == 1])
        total_work_time = sum([s[3] for s in sessions if s[2] == 'work' and s[4] == 1])
        success_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        self.total_sessions_label.setText(f"Toplam Oturum\n{total_sessions}")
        self.completed_sessions_label.setText(f"Tamamlanan\n{completed_sessions}")
        self.total_work_time_label.setText(f"Toplam Çalışma\n{total_work_time} dakika")
        self.success_rate_label.setText(f"Başarı Oranı\n{success_rate:.1f}%")
        
        # Update recent sessions
        recent_text = ""
        for session in sessions[:10]:  # Show last 10 sessions
            date = datetime.fromisoformat(session[1]).strftime("%d.%m.%Y %H:%M")
            session_type = session[2]
            duration = session[3]
            completed = "✅" if session[4] == 1 else "❌"
            task_name = session[5] if session[5] else "Görev belirtilmedi"
            
            recent_text += f"{date} - {session_type.title()} ({duration} dk) {completed} - {task_name}\n"
        
        self.recent_sessions.setPlainText(recent_text)
        
    def open_settings(self):
        dialog = SettingsDialog(self.db_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_settings()
            
    def start_timer(self):
        if not self.is_running:
            duration = self.get_current_duration()
            self.timer_thread.start_timer(duration * 60)
            self.is_running = True
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.status_label.setText(f"{self.session_type.title()} oturumu başladı")
        elif self.timer_thread.is_paused:
            self.timer_thread.resume_timer()
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.status_label.setText("Devam ediyor")
            
    def pause_timer(self):
        if self.is_running and not self.timer_thread.is_paused:
            self.timer_thread.pause_timer()
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶️ Devam Et")
            self.pause_btn.setEnabled(False)
            self.status_label.setText("Durakladı")
        elif self.is_running and self.timer_thread.is_paused:
            self.timer_thread.resume_timer()
            self.start_btn.setEnabled(False)
            self.start_btn.setText("▶️ Başlat")
            self.pause_btn.setEnabled(True)
            self.status_label.setText("Devam ediyor")
            
    def reset_timer(self):
        self.timer_thread.stop_timer()
        self.is_running = False
        self.start_btn.setEnabled(True)
        self.start_btn.setText("▶️ Başlat")
        self.pause_btn.setEnabled(False)
        
        duration = self.get_current_duration()
        self.update_timer_display(duration * 60)
        self.status_label.setText("Sıfırlandı")
        
    def get_current_duration(self):
        if self.session_type == "work":
            return self.work_duration
        elif self.session_type == "short_break":
            return self.short_break_duration
        else:  # long_break
            return self.long_break_duration
            
    def update_timer_display(self, seconds):
        minutes = seconds // 60
        secs = seconds % 60
        self.time_label.setText(f"{minutes:02d}:{secs:02d}")
        
        # Update progress bar
        total_seconds = self.get_current_duration() * 60
        self.progress_bar.set_progress(seconds, total_seconds)
        
    def timer_finished(self):
        self.is_running = False
        self.start_btn.setEnabled(True)
        self.start_btn.setText("▶️ Başlat")
        self.pause_btn.setEnabled(False)
        
        # Save session to database
        task_name = self.task_input.text()
        duration = self.get_current_duration()
        self.db_manager.add_session(self.session_type, duration, 1, task_name)
        
        # Move to next session
        self.move_to_next_session()
        
        # Update stats
        self.update_profile_stats()
        self.stats_tab.update_charts()
        
        self.status_label.setText(f"{self.session_type.title()} oturumu tamamlandı!")
        
    def move_to_next_session(self):
        if self.session_type == "work":
            self.current_session += 1
            
            if self.current_session % self.long_break_interval == 0:
                self.session_type = "long_break"
                self.session_label.setText("Uzun Mola")
                self.session_label.setStyleSheet("""
                    QLabel {
                        font-size: 24px;
                        font-weight: bold;
                        color: #9C27B0;
                        margin: 20px;
                    }
                """)
            else:
                self.session_type = "short_break"
                self.session_label.setText("Kısa Mola")
                self.session_label.setStyleSheet("""
                    QLabel {
                        font-size: 24px;
                        font-weight: bold;
                        color: #2196F3;
                        margin: 20px;
                    }
                """)
        else:
            self.session_type = "work"
            self.session_label.setText("Çalışma Oturumu")
            self.session_label.setStyleSheet("""
                QLabel {
                    font-size: 24px;
                    font-weight: bold;
                    color: #4CAF50;
                    margin: 20px;
                }
            """)
            
        # Update session counter
        self.session_counter.setText(f"Oturum: {self.current_session}/{self.long_break_interval}")
        
        # Update timer display
        duration = self.get_current_duration()
        self.update_timer_display(duration * 60)
        
        # Auto-start if enabled
        if ((self.session_type != "work" and self.auto_start_breaks) or 
            (self.session_type == "work" and self.auto_start_work)):
            self.start_timer()


def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    # Create and show the main window
    window = PomodoroApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()