"""
Trade Analyzer - Analyzes historical trade performance
Identifies patterns in profitable vs unprofitable trades
"""

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
import logging


class TradeAnalyzer:
    """Analyzes historical trades to identify patterns and insights"""

    def __init__(self, db_path: str = '/var/lib/trading-bot/trading_bot.db'):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

    def get_all_closed_positions(self, days: Optional[int] = None) -> List[Dict]:
        """Get all closed positions, optionally filtered by days"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = '''
            SELECT * FROM positions
            WHERE status = 'closed' AND pnl IS NOT NULL
        '''

        if days:
            query += f" AND DATE(closed_at) >= DATE('now', '-{days} days', 'localtime')"

        query += " ORDER BY closed_at DESC"

        cursor.execute(query)
        positions = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return positions

    def analyze_performance(self, days: Optional[int] = None) -> Dict:
        """Analyze overall trading performance"""
        positions = self.get_all_closed_positions(days)

        if not positions:
            return {
                'total_trades': 0,
                'profitable_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_profit': 0.0,
                'avg_loss': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0
            }

        profitable = [p for p in positions if p['pnl'] > 0]
        losing = [p for p in positions if p['pnl'] < 0]

        total_pnl = sum(p['pnl'] for p in positions)
        total_invested = sum(p['entry_price'] * p['quantity'] for p in positions)
        avg_profit = sum(p['pnl'] for p in profitable) / len(profitable) if profitable else 0
        avg_loss = sum(p['pnl'] for p in losing) / len(losing) if losing else 0

        return {
            'total_trades': len(positions),
            'profitable_trades': len(profitable),
            'losing_trades': len(losing),
            'win_rate': (
                len(profitable) / len(positions) * 100) if positions else 0,
            'total_pnl': total_pnl,
            'total_invested': total_invested,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'best_trade': max(
                p['pnl'] for p in positions),
            'worst_trade': min(
                p['pnl'] for p in positions),
            'profit_factor': abs(
                sum(
                    p['pnl'] for p in profitable) / sum(
                    p['pnl'] for p in losing)) if losing and sum(
                p['pnl'] for p in losing) != 0 else float('inf')}

    def analyze_by_symbol(self, days: Optional[int] = None) -> Dict[str, Dict]:
        """Analyze performance by trading pair"""
        positions = self.get_all_closed_positions(days)

        symbol_stats = {}

        for position in positions:
            symbol = position['symbol']
            if symbol not in symbol_stats:
                symbol_stats[symbol] = {
                    'trades': [],
                    'profitable': 0,
                    'losing': 0,
                    'total_pnl': 0.0
                }

            symbol_stats[symbol]['trades'].append(position)
            symbol_stats[symbol]['total_pnl'] += position['pnl']

            if position['pnl'] > 0:
                symbol_stats[symbol]['profitable'] += 1
            else:
                symbol_stats[symbol]['losing'] += 1

        # Calculate summary for each symbol
        results = {}
        for symbol, stats in symbol_stats.items():
            total = len(stats['trades'])
            results[symbol] = {
                'total_trades': total,
                'profitable_trades': stats['profitable'],
                'losing_trades': stats['losing'],
                'win_rate': (stats['profitable'] / total * 100) if total > 0 else 0,
                'total_pnl': stats['total_pnl'],
                'avg_pnl': stats['total_pnl'] / total if total > 0 else 0
            }

        # Sort by total P&L
        results = dict(sorted(results.items(), key=lambda x: x[1]['total_pnl'], reverse=True))

        return results

    def analyze_by_strategy(self, days: Optional[int] = None) -> Dict[str, Dict]:
        """Analyze performance by strategy"""
        positions = self.get_all_closed_positions(days)

        strategy_stats = {}

        for position in positions:
            strategy = position.get('strategy', 'Unknown')
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {
                    'trades': [],
                    'profitable': 0,
                    'losing': 0,
                    'total_pnl': 0.0
                }

            strategy_stats[strategy]['trades'].append(position)
            strategy_stats[strategy]['total_pnl'] += position['pnl']

            if position['pnl'] > 0:
                strategy_stats[strategy]['profitable'] += 1
            else:
                strategy_stats[strategy]['losing'] += 1

        # Calculate summary for each strategy
        results = {}
        for strategy, stats in strategy_stats.items():
            total = len(stats['trades'])
            results[strategy] = {
                'total_trades': total,
                'profitable_trades': stats['profitable'],
                'losing_trades': stats['losing'],
                'win_rate': (stats['profitable'] / total * 100) if total > 0 else 0,
                'total_pnl': stats['total_pnl'],
                'avg_pnl': stats['total_pnl'] / total if total > 0 else 0
            }

        return results

    def find_common_patterns_in_profitable_trades(self, min_pnl: float = 0) -> Dict:
        """Identify common characteristics in profitable trades"""
        positions = self.get_all_closed_positions()
        profitable = [p for p in positions if p['pnl'] and p['pnl'] > min_pnl]

        if not profitable:
            return {}

        # Analyze holding time patterns
        holding_times = []
        for p in profitable:
            if p['opened_at'] and p['closed_at']:
                try:
                    # Handle different datetime formats
                    opened_str = str(p['opened_at']).strip()
                    closed_str = str(p['closed_at']).strip()

                    # Skip if empty or None
                    if not opened_str or opened_str.lower() == 'none' or not closed_str or closed_str.lower() == 'none':
                        continue

                    opened = datetime.fromisoformat(opened_str.replace(' ', 'T'))
                    closed = datetime.fromisoformat(closed_str.replace(' ', 'T'))
                    holding_time = (closed - opened).total_seconds() / 3600  # hours
                    holding_times.append(holding_time)
                except (ValueError, AttributeError) as e:
                    # Skip positions with invalid datetime formats
                    self.logger.debug(
                        f"Could not parse datetime for position {p.get('id', 'unknown')}: {e}")
                    continue

        avg_holding_time = sum(holding_times) / len(holding_times) if holding_times else 0

        # Analyze by side
        long_trades = [p for p in profitable if p['side'] == 'BUY']
        short_trades = [p for p in profitable if p['side'] == 'SELL']

        return {
            'total_profitable': len(profitable),
            'avg_holding_time_hours': avg_holding_time,
            'long_trades': len(long_trades),
            'short_trades': len(short_trades),
            'avg_profit_long': sum(
                p['pnl'] for p in long_trades) /
            len(long_trades) if long_trades else 0,
            'avg_profit_short': sum(
                p['pnl'] for p in short_trades) /
            len(short_trades) if short_trades else 0}

    def get_recommendations(self) -> List[str]:
        """Generate recommendations based on analysis"""
        recommendations = []

        # Analyze overall performance
        overall = self.analyze_performance(days=30)

        if overall['total_trades'] == 0:
            recommendations.append("⚠️ No trades found. Bot needs to accumulate trading history.")
            return recommendations

        # Win rate analysis
        if overall['win_rate'] < 50:
            recommendations.append(
                f"⚠️ Win rate is {overall['win_rate']:.1f}%. Consider adjusting strategy parameters.")
        elif overall['win_rate'] > 70:
            recommendations.append(f"✅ Excellent win rate of {overall['win_rate']:.1f}%!")

        # Profit factor analysis
        if overall['profit_factor'] < 1.5:
            recommendations.append(
                f"⚠️ Profit factor is {overall['profit_factor']:.2f}. Aim for >1.5 for sustainable profitability.")
        elif overall['profit_factor'] > 2.0:
            recommendations.append(f"✅ Strong profit factor of {overall['profit_factor']:.2f}!")

        # Symbol performance
        symbol_stats = self.analyze_by_symbol(days=30)
        if symbol_stats:
            best_symbol = max(symbol_stats.items(), key=lambda x: x[1]['total_pnl'])
            worst_symbol = min(symbol_stats.items(), key=lambda x: x[1]['total_pnl'])

            recommendations.append(
                f"📈 Best performing pair: {best_symbol[0]} (P&L: ${best_symbol[1]['total_pnl']:.2f})")
            if worst_symbol[1]['total_pnl'] < 0:
                recommendations.append(
                    f"📉 Worst performing pair: {worst_symbol[0]} (P&L: ${worst_symbol[1]['total_pnl']:.2f}) - Consider disabling or adjusting strategy")

        # Average win vs loss
        if abs(overall['avg_loss']) > overall['avg_profit']:
            recommendations.append(
                f"⚠️ Average loss (${abs(overall['avg_loss']):.2f}) exceeds average profit (${overall['avg_profit']:.2f}). Improve risk/reward ratio.")

        return recommendations
