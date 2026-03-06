"""
Performance Analyzer - Advanced performance metrics and analysis
"""

from typing import Dict, Optional
import sqlite3


class PerformanceAnalyzer:
    """Analyzes trading performance with advanced metrics"""

    def __init__(self, db_path: str = '/var/lib/trading-bot/trading_bot.db'):
        self.db_path = db_path

    def calculate_sharpe_ratio(self, days: int = 30) -> float:
        """Calculate Sharpe ratio (risk-adjusted return)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT pnl, DATE(closed_at) as date
            FROM positions
            WHERE status = 'closed'
            AND pnl IS NOT NULL
            AND DATE(closed_at) >= DATE('now', '-' || ? || ' days', 'localtime')
            ORDER BY closed_at
        ''', (days,))

        trades = cursor.fetchall()
        conn.close()

        if not trades:
            return 0.0

        daily_returns = {}
        for pnl, date in trades:
            if date not in daily_returns:
                daily_returns[date] = 0
            daily_returns[date] += pnl

        returns = list(daily_returns.values())

        if len(returns) < 2:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return 0.0

        sharpe = mean_return / std_dev
        sharpe_annualized = sharpe * (252 ** 0.5)

        return sharpe_annualized

    def calculate_max_drawdown(self, days: Optional[int] = None) -> Dict:
        """Calculate maximum drawdown"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = '''
            SELECT pnl, closed_at
            FROM positions
            WHERE status = 'closed'
            AND pnl IS NOT NULL
        '''

        if days:
            query += f" AND DATE(closed_at) >= DATE('now', '-{days} days', 'localtime')"

        query += " ORDER BY closed_at"

        cursor.execute(query)
        trades = cursor.fetchall()
        conn.close()

        if not trades:
            return {'max_drawdown': 0.0, 'max_drawdown_pct': 0.0}

        # Calculate cumulative P&L
        cumulative = 0
        peak = 0
        max_dd = 0

        for pnl, _ in trades:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0

        return {
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd_pct
        }

    def get_win_streak_stats(self) -> Dict:
        """Analyze winning and losing streaks"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT pnl FROM positions
            WHERE status = 'closed' AND pnl IS NOT NULL
            ORDER BY closed_at
        ''')

        trades = cursor.fetchall()
        conn.close()

        if not trades:
            return {
                'max_win_streak': 0,
                'max_loss_streak': 0,
                'current_streak': 0,
                'current_streak_type': 'none'
            }

        current_streak = 0
        current_type = None
        max_win_streak = 0
        max_loss_streak = 0

        for (pnl,) in trades:
            if pnl > 0:
                if current_type == 'win':
                    current_streak += 1
                else:
                    current_type = 'win'
                    current_streak = 1
                max_win_streak = max(max_win_streak, current_streak)
            elif pnl < 0:
                if current_type == 'loss':
                    current_streak += 1
                else:
                    current_type = 'loss'
                    current_streak = 1
                max_loss_streak = max(max_loss_streak, current_streak)

        return {
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak,
            'current_streak': current_streak,
            'current_streak_type': current_type or 'none'
        }

    def get_performance_summary(self, days: int = 30) -> Dict:
        """Get comprehensive performance summary"""
        sharpe = self.calculate_sharpe_ratio(days)
        drawdown = self.calculate_max_drawdown(days)
        streaks = self.get_win_streak_stats()

        return {
            'sharpe_ratio': sharpe,
            'max_drawdown': drawdown['max_drawdown'],
            'max_drawdown_pct': drawdown['max_drawdown_pct'],
            'max_win_streak': streaks['max_win_streak'],
            'max_loss_streak': streaks['max_loss_streak'],
            'current_streak': {
                'type': streaks['current_streak_type'],
                'count': streaks['current_streak']
            }
        }
