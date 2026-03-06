"""
Trading Bot Core
Main bot class that coordinates all components
"""

import time
import logging
import os
import asyncio
import threading
from datetime import datetime

from core.config import Config
from core.database import Database
from core.risk_manager import RiskManager
from core.exchange_adapter import ExchangeAdapter
from strategies.strategy_manager import StrategyManager
from utils.notifications import init_notifier


class TradingBot:
    """Main trading bot class"""

    def __init__(self, config: Config):
        """
        Initialize trading bot

        Args:
            config: Configuration object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.last_hourly_notification = None
        self.news_aggregator_thread = None
        self.news_aggregator_loop = None

        if not config.validate():
            raise ValueError("Invalid configuration")

        self.logger.info("Initializing trading bot components...")

        self.db = Database(config)
        self.logger.info("Database initialized")

        try:
            self.exchange = ExchangeAdapter(config)
            self.exchange.ping()

            exchange_name = config.exchange_id if config.use_ccxt else 'Binance'
            testnet_str = 'TESTNET' if config.exchange_testnet else 'PRODUCTION'
            mode_str = 'CCXT' if config.use_ccxt else 'Legacy'

            self.logger.info(f"Connected to {exchange_name} {testnet_str} ({mode_str})")
        except Exception as e:
            self.logger.error(f"Failed to initialize exchange: {e}")
            raise

        self.client = self.exchange

        self.risk_manager = RiskManager(config, self.db, self.exchange)
        self.logger.info("Risk manager initialized")

        self.strategy_manager = StrategyManager(config, self.exchange, self.db, self.risk_manager)
        self.logger.info("Strategy manager initialized")

        try:
            from mi import AdaptiveTacticsManager
            self.adaptive_tactics = AdaptiveTacticsManager(config, self.db, self.logger)
            self.logger.info("Adaptive tactics manager initialized")
        except Exception as e:
            self.logger.warning(f"Adaptive tactics not available: {e}")
            self.adaptive_tactics = None

        try:
            from mi.strategy_advisor import StrategyAdvisor
            config_dict = {
                'ADAPTIVE_STRATEGY_ENABLED': config.get('ADAPTIVE_STRATEGY_ENABLED', True),
                'ADAPTIVE_ADJUSTMENT_INTERVAL': config.get('ADAPTIVE_ADJUSTMENT_INTERVAL', 3600),
                'ADAPTIVE_AGGRESSIVE_MODE': config.get('ADAPTIVE_AGGRESSIVE_MODE', False),
            }
            self.strategy_advisor = StrategyAdvisor(config_dict)
            self.logger.info("Strategy advisor initialized")
        except Exception as e:
            self.logger.warning(f"Strategy advisor not available: {e}")
            self.strategy_advisor = None

        enable_elite_ai = os.getenv('ENABLE_ELITE_AI', 'false').lower() == 'true'
        self.elite_integrator = None

        if enable_elite_ai:
            self.logger.info("=" * 60)
            self.logger.info("🔍 ELITE AI ENABLED - Attempting initialization...")
            self.logger.info(
                f"  ENABLE_ELITE_RISK_MANAGEMENT = {os.getenv('ENABLE_ELITE_RISK_MANAGEMENT', 'false')}")
            self.logger.info(
                f"  ENABLE_REGIME_DETECTION = {os.getenv('ENABLE_REGIME_DETECTION', 'false')}")
            self.logger.info(f"  ENABLE_MTF_ANALYSIS = {os.getenv('ENABLE_MTF_ANALYSIS', 'false')}")
            self.logger.info(
                f"  ENABLE_ELITE_POSITION_MGMT = {os.getenv('ENABLE_ELITE_POSITION_MGMT', 'false')}")
            self.logger.info("=" * 60)

            try:
                self.logger.info("📦 Importing EliteBotIntegrator...")
                from core.elite_bot_integrator import EliteBotIntegrator
                self.logger.info("✓ EliteBotIntegrator imported successfully")

                self.logger.info("🔧 Creating EliteBotIntegrator instance...")
                self.elite_integrator = EliteBotIntegrator(self.exchange, config)
                self.logger.info("✓ EliteBotIntegrator instance created")

                # Log Elite AI status
                self.logger.info("🌟 Elite AI initialized - Advanced trading features active")
                self.logger.info(
                    f"  ✓ Elite Risk Management: {self.elite_integrator.elite_risk_mgr is not None}")
                self.logger.info(
                    f"  ✓ Regime Detection: {self.elite_integrator.regime_detector is not None}")
                self.logger.info(
                    f"  ✓ MTF Analysis: {self.elite_integrator.mtf_analyzer is not None}")
                self.logger.info(
                    f"  ✓ Elite Position Mgmt: {self.elite_integrator.elite_position_mgr is not None}")

            except ImportError as e:
                self.logger.warning(f"⚠️ Failed to import Elite AI modules: {e}")
                self.logger.warning("   Elite AI disabled - bot will run with standard features")
                self.elite_integrator = None
            except Exception as e:
                self.logger.warning(f"⚠️ Elite AI initialization failed: {e}")
                self.logger.warning("   Elite AI disabled - bot will run with standard features")
                self.elite_integrator = None
        else:
            self.logger.info("ℹ️ Elite AI DISABLED (set ENABLE_ELITE_AI=true to enable)")

        if self.elite_integrator is None:
            self.logger.info("✓ Bot initialized in STANDARD MODE (without Elite AI)")

        # Initialize News Aggregator
        enable_news = os.getenv('ENABLE_NEWS_ANALYSIS', 'true').lower() == 'true'
        self.news_aggregator = None
        self.news_error_message = None  # Store error for notifications
        if enable_news:
            try:
                self.logger.info("=" * 80)
                self.logger.info("🚨 ATTEMPTING TO INITIALIZE NEWS AGGREGATOR...")
                self.logger.info(
                    f"   ENABLE_NEWS_ANALYSIS = {os.getenv('ENABLE_NEWS_ANALYSIS', 'not set')}")
                self.logger.info("=" * 80)

                from news.news_aggregator import NewsAggregator
                self.logger.info("✅ SUCCESS: NewsAggregator module imported!")

                # Prepare config for news aggregator
                news_config = {
                    'CRYPTOPANIC_API_KEY': os.getenv('CRYPTOPANIC_API_KEY', ''),
                    'NEWSAPI_API_KEY': os.getenv('NEWSAPI_API_KEY', ''),
                }

                db_path = config.db_path if hasattr(
                    config, 'db_path') else '/var/lib/trading-bot/trading_bot.db'
                self.logger.info(f"   Creating NewsAggregator with db: {db_path}")
                self.news_aggregator = NewsAggregator(db_path=db_path, config=news_config)
                self.logger.info("=" * 80)
                self.logger.info("✅✅✅ SUCCESS: News Aggregator INITIALIZED!")
                self.logger.info("   News analysis WILL appear in hourly notifications")
                self.logger.info("=" * 80)

            except ImportError as e:
                self.news_error_message = f"Missing dependencies: {str(e)}"
                self.logger.error("=" * 80)
                self.logger.error("❌❌❌ CRITICAL: NewsAggregator import FAILED!")
                self.logger.error(f"   Error: {e}")
                self.logger.error("")
                self.logger.error("   🔧 TO FIX THIS, RUN:")
                self.logger.error("")
                self.logger.error("   cd /opt/trading-bot")
                self.logger.error("   source venv/bin/activate")
                self.logger.error("   pip install aiohttp feedparser")
                self.logger.error("   deactivate")
                self.logger.error("   sudo systemctl restart trading-bot")
                self.logger.error("")
                self.logger.error("   News analysis is DISABLED until dependencies are installed")
                self.logger.error("=" * 80)
                self.news_aggregator = None
            except Exception as e:
                self.news_error_message = f"Init failed: {str(e)}"
                self.logger.error("=" * 80)
                self.logger.error("❌❌❌ CRITICAL: NewsAggregator initialization FAILED!")
                self.logger.error(f"   Error: {e}")
                self.logger.error("   News analysis is DISABLED")
                self.logger.error("=" * 80)
                self.news_aggregator = None
        else:
            self.news_error_message = "Disabled in .env"
            self.logger.info("ℹ️ News Analysis DISABLED (set ENABLE_NEWS_ANALYSIS=true to enable)")

        # Initialize Telegram notifications
        telegram_enabled = config.enable_notifications
        if telegram_enabled:
            telegram_token = config.telegram_bot_token
            telegram_chat_id = config.telegram_chat_id
            self.notifier = init_notifier(telegram_token, telegram_chat_id, telegram_enabled)
            if self.notifier and self.notifier.enabled:
                self.logger.info("Telegram notifications initialized")
            else:
                self.logger.warning("Telegram notifications not available")
                self.notifier = None
        else:
            self.notifier = None
            self.logger.info("Telegram notifications disabled")

        self.logger.info("Trading bot initialization complete")

    def _start_news_aggregator_background(self):
        """Start news aggregator in a background thread with its own event loop"""
        if not self.news_aggregator:
            return

        def run_news_aggregator():
            """Run news aggregator in background thread"""
            try:
                self.logger.info("=" * 70)
                self.logger.info("🚀 STARTING NEWS AGGREGATOR BACKGROUND TASK...")
                self.logger.info("=" * 70)

                # Create new event loop for this thread
                self.news_aggregator_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.news_aggregator_loop)

                # Start the news aggregator
                self.news_aggregator_loop.run_until_complete(self.news_aggregator.start())

                # Do an initial fetch immediately
                self.logger.info("📰 Performing initial news fetch...")
                self.news_aggregator_loop.run_until_complete(self.news_aggregator.fetch_all_news())

                # Keep the loop running for background tasks
                self.news_aggregator_loop.run_forever()

            except Exception as e:
                self.logger.error(
                    f"❌ Error in news aggregator background thread: {e}",
                    exc_info=True)
            finally:
                if self.news_aggregator_loop:
                    self.news_aggregator_loop.close()

        # Start in background thread
        self.news_aggregator_thread = threading.Thread(target=run_news_aggregator, daemon=True)
        self.news_aggregator_thread.start()
        self.logger.info("✅ News aggregator thread started")

    def _stop_news_aggregator_background(self):
        """Stop the news aggregator background task"""
        if self.news_aggregator and self.news_aggregator_loop:
            try:
                self.logger.info("Stopping news aggregator...")
                # stop() is a synchronous method, call it directly
                self.news_aggregator.stop()
                # Stop the event loop
                if self.news_aggregator_loop and self.news_aggregator_loop.is_running():
                    self.news_aggregator_loop.call_soon_threadsafe(self.news_aggregator_loop.stop)
                self.logger.info("News aggregator stopped")
            except Exception as e:
                self.logger.error(f"Error stopping news aggregator: {e}")

    def start(self):
        """Start the trading bot"""
        self.logger.info("=" * 70)
        self.logger.info("TRADING BOT STARTED")
        self.logger.info("=" * 70)
        exchange_name = self.config.exchange_id if self.config.use_ccxt else 'Binance'
        self.logger.info(f"Exchange: {exchange_name}")
        self.logger.info(f"Mode: {'CCXT' if self.config.use_ccxt else 'Legacy'}")
        self.logger.info(f"Trading enabled: {self.config.trading_enabled}")
        self.logger.info(f"Default symbol: {self.config.default_symbol}")
        self.logger.info(f"Max open positions: {self.config.max_open_positions}")
        self.logger.info(f"Max daily trades: {self.config.max_daily_trades}")
        self.logger.info("=" * 70)

        # Start news aggregator background task
        self._start_news_aggregator_background()

        # Send startup notification
        if self.notifier:
            self.notifier.notify_bot_started(
                exchange=exchange_name,
                trading_enabled=self.config.trading_enabled,
                max_positions=self.config.max_open_positions,
                max_daily_trades=self.config.max_daily_trades,
                strategy=self.config.active_strategy
            )

        self.running = True

        try:
            # Get account info
            account = self.exchange.get_account()
            self.logger.info(f"Account status: Can trade: {account.get('canTrade', True)}")

            # Main loop
            while self.running:
                try:
                    # Send hourly status update
                    self._send_hourly_notification_if_needed()

                    # Check risk limits
                    if not self.risk_manager.check_daily_limits():
                        self.logger.warning("Daily risk limits reached, skipping trading cycle")
                        time.sleep(60)
                        continue

                    # Run strategy evaluation
                    if self.config.trading_enabled:
                        self.strategy_manager.evaluate_strategies()
                    else:
                        self.logger.debug("Trading disabled, running in monitoring mode only")

                    # Health check
                    if self.config.health_check_enabled:
                        self._health_check()

                    # Sleep before next cycle
                    time.sleep(60)  # Check every minute

                except KeyboardInterrupt:
                    self.logger.info("Shutdown requested")
                    break
                except Exception as e:
                    error_msg = str(e)
                    self.logger.error(f"Error in main loop: {error_msg}", exc_info=True)
                    # Send error notification
                    if self.notifier:
                        self.notifier.notify_error("Main Loop Error", error_msg)
                    time.sleep(60)

        finally:
            self.stop()

    def stop(self):
        """Stop the trading bot"""
        self.logger.info("Stopping trading bot...")
        self.running = False

        # Stop news aggregator
        self._stop_news_aggregator_background()

        # Send shutdown notification
        if hasattr(self, 'notifier') and self.notifier:
            self.notifier.notify_bot_stopped("Normal shutdown")

        # Close all positions if configured
        if hasattr(self, 'strategy_manager'):
            self.strategy_manager.close_all_positions()

        # Close database connection
        if hasattr(self, 'db'):
            self.db.close()

        self.logger.info("Trading bot stopped")

    def _send_hourly_notification_if_needed(self):
        """Send hourly status notification if an hour has passed"""
        if not self.notifier or not self.notifier.enabled:
            return

        try:
            current_time = datetime.now()

            # Check if an hour has passed since last notification
            if self.last_hourly_notification is None or \
               (current_time - self.last_hourly_notification).total_seconds() >= 3600:

                self.logger.info("Sending hourly status notification...")

                # Get open positions count
                open_positions = self.db.get_open_positions()
                open_positions_count = len(open_positions)

                # Get account balances
                try:
                    balance_data = {}
                    account_balance = self.exchange.fetch_balance()

                    # Extract balances from CCXT format
                    if 'free' in account_balance:
                        for currency, amount in account_balance['free'].items():
                            if amount and float(amount) > 0:
                                balance_data[currency] = amount
                    elif 'balances' in account_balance:
                        # Binance legacy format
                        for balance in account_balance['balances']:
                            free_amount = float(balance.get('free', 0))
                            if free_amount > 0:
                                balance_data[balance['asset']] = free_amount
                    else:
                        # Fallback: try direct balance dictionary
                        for key, value in account_balance.items():
                            if isinstance(
                                    value, (int, float, str)) and key not in [
                                    'info', 'timestamp', 'datetime']:
                                try:
                                    amount = float(value)
                                    if amount > 0:
                                        balance_data[key] = amount
                                except (ValueError, TypeError):
                                    pass

                    # If no balances found, add USDT as 0
                    if not balance_data:
                        balance_data = {'USDT': 0}

                except Exception as e:
                    self.logger.error(f"Error fetching balances: {e}")
                    balance_data = {'USDT': 0}

                # Record a daily balance snapshot for monthly ROI calculation
                try:
                    usdt_balance = float(balance_data.get('USDT', 0))
                    if usdt_balance > 0:
                        self.db.save_balance_snapshot(usdt_balance)
                except Exception as e:
                    self.logger.warning(f"Could not save balance snapshot: {e}")

                # Get daily P/L
                daily_pnl = self.db.get_daily_profit_loss()

                # Get daily trade count to show activity in hourly notification
                try:
                    daily_trades = self.db.get_daily_trade_count()
                except Exception as e:
                    self.logger.warning(f"Could not get daily trade count: {e}")
                    daily_trades = None

                # Analyze market trends
                trends = None
                try:
                    self.logger.info("Analyzing market trends for hourly report...")
                    trends = self.strategy_manager.analyze_market_trends()
                except Exception as e:
                    self.logger.error(f"Error analyzing trends: {e}", exc_info=True)

                # Run adaptive tactics analysis (hourly)
                ai_tactics = None
                if self.adaptive_tactics:
                    try:
                        self.logger.info("Running adaptive tactics analysis...")
                        adjustments = self.adaptive_tactics.analyze_and_adjust()

                        if adjustments.get('adjustments'):
                            # Log adjustments
                            self.logger.info("🤖 Adaptive tactics made adjustments:")
                            for adj in adjustments['adjustments']:
                                self.logger.info(f"   {adj}")

                            # Update strategy manager with tactical overrides
                            self.strategy_manager.set_tactical_overrides(self.adaptive_tactics)

                        # Get current tactics for notification
                        ai_tactics = self.adaptive_tactics.get_current_tactics()

                    except Exception as e:
                        self.logger.error(f"Error in adaptive tactics: {e}", exc_info=True)

                # Initialize strategy_adjustments
                strategy_adjustments = None

                # Run strategy advisor analysis (converts AI insights into strategy adjustments)
                if self.strategy_advisor:
                    try:
                        self.logger.info("Running strategy advisor analysis...")

                        # Prepare market data
                        market_data = {
                            'avg_volatility': 0,
                            'trend_strength': 'normal',
                            'trend_summary': ''
                        }
                        if trends:
                            # trends is a dict: {symbol: trend_info_dict}
                            trend_strengths = []
                            for symbol, trend_info in trends.items():
                                strength = trend_info.get('strength')
                                if strength is None:
                                    self.logger.warning(f"Trend info for {symbol} missing 'strength' key")
                                    strength = 0
                                trend_strengths.append(abs(strength))

                            if trend_strengths:
                                avg_strength = sum(trend_strengths) / len(trend_strengths)
                                # strength is 0-1 scale; convert to 0-100 for comparison
                                avg_strength_pct = avg_strength * 100
                                market_data['avg_volatility'] = avg_strength_pct

                                if avg_strength_pct > 70:
                                    market_data['trend_strength'] = 'strong'
                                elif avg_strength_pct < 40:
                                    market_data['trend_strength'] = 'weak'

                        # Prepare performance data using PerformanceAnalyzer for real metrics
                        performance_data = {
                            'daily_pnl': daily_pnl,
                            'weekly_pnl': 0,
                            'win_rate': 50,
                            'max_drawdown_pct': 0,
                            'sharpe_ratio': 0
                        }

                        # Get performance metrics from database and PerformanceAnalyzer
                        try:
                            metrics = self.db.get_performance_metrics()
                            if metrics:
                                performance_data['win_rate'] = metrics.get('win_rate', 50)

                            # Use PerformanceAnalyzer for sharpe, drawdown, weekly pnl
                            try:
                                from mi import TradeAnalyzer, PerformanceAnalyzer
                                trade_analyzer = TradeAnalyzer(db_path=self.config.db_path)
                                perf_analyzer = PerformanceAnalyzer(db_path=self.config.db_path)
                                perf_7d = trade_analyzer.analyze_performance(days=7)
                                adv_metrics = perf_analyzer.get_performance_summary()
                                if perf_7d:
                                    performance_data['weekly_pnl'] = perf_7d.get('total_pnl', 0)
                                    performance_data['win_rate'] = perf_7d.get('win_rate', performance_data['win_rate'])
                                if adv_metrics:
                                    performance_data['max_drawdown_pct'] = adv_metrics.get('max_drawdown_pct', 0)
                                    performance_data['sharpe_ratio'] = adv_metrics.get('sharpe_ratio', 0)
                            except Exception as e:
                                self.logger.warning(f"Could not get advanced performance metrics: {e}")
                        except Exception as e:
                            self.logger.warning(f"Could not get performance metrics: {e}")

                        # Get strategy recommendations
                        advice = self.strategy_advisor.analyze_and_advise(
                            market_data, performance_data)

                        # Store strategy adjustments for notification
                        strategy_adjustments = advice

                        # Log strategy adjustments for debugging
                        self.logger.info(f"📊 Strategy Advisor returned: {strategy_adjustments}")

                        if advice and advice.get('adjustments'):
                            self.logger.info("📊 Strategy Advisor recommendations:")
                            self.logger.info(f"   Risk Level: {advice['risk_level'].upper()}")

                            for key, value in advice['adjustments'].items():
                                self.logger.info(f"   {key}: {value}")

                            for rec in advice.get('recommendations', []):
                                self.logger.info(f"   {rec}")

                            # Apply strategy adjustments to strategy manager
                            try:
                                if hasattr(self.strategy_manager, 'apply_strategy_adjustments'):
                                    self.strategy_manager.apply_strategy_adjustments(
                                        advice['adjustments'])
                                else:
                                    self.logger.warning("apply_strategy_adjustments not available on strategy_manager")
                            except Exception as apply_error:
                                self.logger.error(
                                    f"Error applying strategy adjustments: {apply_error}")
                                # Don't let this error prevent notification

                    except Exception as e:
                        self.logger.error(f"Error in strategy advisor: {e}", exc_info=True)

                # Run Elite AI analysis (if enabled)
                elite_ai_data = None
                if self.elite_integrator:
                    try:
                        self.logger.info("🌟 Running Elite AI analysis...")

                        # Initialize Elite AI data dictionary
                        elite_ai_data = {
                            'regimes': {},
                            'mtf_analysis': {},
                            'risk_management': False,
                            'position_management': False,
                            'monitored_positions': 0
                        }

                        # Get list of trading symbols (already a list in config)
                        symbols = self.config.trading_symbols if hasattr(self.config, 'trading_symbols') else [
                            self.config.default_symbol]

                        # Market Regime Detection
                        if self.elite_integrator.regime_detector:
                            self.logger.info("📊 Regime Detection: Analyzing market conditions...")
                            for symbol in symbols[:3]:  # Analyze top 3 symbols
                                try:
                                    regime_data = self.elite_integrator.detect_market_regime(symbol)
                                    if regime_data:
                                        regime_name = str(regime_data.get('regime', 'UNKNOWN'))
                                        if hasattr(regime_data.get('regime'), 'value'):
                                            regime_name = regime_data['regime'].value
                                        confidence = regime_data.get('confidence', 0) * 100
                                        trending = regime_data.get('trending', False)
                                        volatile = regime_data.get('volatile', False)
                                        self.logger.info(
                                            f"  {symbol}: {regime_name.upper()} "
                                            f"(Confidence: {confidence:.1f}%, "
                                            f"Trending: {trending}, Volatile: {volatile})")
                                        # Store for notification
                                        elite_ai_data['regimes'][symbol] = {
                                            'regime': regime_name.upper(),
                                            'confidence': confidence,
                                            'trending': trending,
                                            'volatile': volatile
                                        }
                                except Exception as e:
                                    self.logger.error(f"Error detecting regime for {symbol}: {e}")

                        # Multi-Timeframe Analysis
                        if self.elite_integrator.mtf_analyzer:
                            self.logger.info("📈 MTF Analysis: Checking trend alignment...")
                            for symbol in symbols[:3]:  # Analyze top 3 symbols
                                try:
                                    # Validate with MTF requires symbol and signal_direction
                                    is_valid, mtf_data = self.elite_integrator.validate_with_mtf(
                                        symbol, 'long')
                                    if mtf_data:
                                        alignment = mtf_data.get('trend_alignment', 0) * 100
                                        recommendation = mtf_data.get('recommendation', 'NEUTRAL')
                                        self.logger.info(
                                            f"  {symbol}: Alignment {alignment:.0f}% "
                                            f"({recommendation}, "
                                            f"{'ALIGNED' if is_valid else 'NOT ALIGNED'})")
                                        # Store for notification
                                        elite_ai_data['mtf_analysis'][symbol] = {
                                            'alignment': alignment,
                                            'recommendation': recommendation,
                                            'is_valid': is_valid
                                        }
                                except Exception as e:
                                    self.logger.error(f"Error in MTF analysis for {symbol}: {e}")

                        # Elite Risk Management
                        if self.elite_integrator.elite_risk_mgr:
                            self.logger.info("💼 Advanced Risk Management: Active")
                            self.logger.info("  ✓ Kelly Criterion position sizing enabled")
                            self.logger.info("  ✓ ATR volatility-based sizing enabled")
                            self.logger.info("  ✓ Portfolio heat management active")
                            elite_ai_data['risk_management'] = True

                        # Elite Position Management
                        if self.elite_integrator.elite_position_mgr:
                            self.logger.info("🎯 Elite Position Management: Active")
                            elite_ai_data['position_management'] = True
                            # Check open positions for updates
                            open_positions = self.db.get_open_positions()
                            elite_ai_data['monitored_positions'] = len(open_positions)
                            if open_positions:
                                self.logger.info(
                                    f"  Monitoring {len(open_positions)} open positions")
                                for pos in open_positions[:3]:  # Show first 3
                                    try:
                                        # Update elite position management
                                        updated = self.elite_integrator.update_position_management(
                                            pos)
                                        if updated:
                                            self.logger.info(
                                                f"  Updated position {pos.get('symbol')}: {updated}")
                                    except Exception as e:
                                        self.logger.error(
                                            f"Error updating position management: {e}")
                            else:
                                self.logger.info("  No open positions to manage")

                        # Store the collected data in self for hourly notifications
                        self.elite_ai_data = elite_ai_data

                        # Log collected data for debugging
                        self.logger.info("📊 Elite AI data collected: "
                                         f"Regimes: {len(elite_ai_data['regimes'])} symbols, "
                                         f"MTF: {len(elite_ai_data['mtf_analysis'])} symbols, "
                                         f"Risk Mgmt: {elite_ai_data['risk_management']}, "
                                         f"Position Mgmt: {elite_ai_data['position_management']}")

                        self.logger.info("🌟 Elite AI analysis complete")

                    except Exception as e:
                        self.logger.error(f"Error in Elite AI analysis: {e}", exc_info=True)
                        # Ensure strategy_adjustments is set even on error
                        if strategy_adjustments is None:
                            strategy_adjustments = {}
                        elite_ai_data = None
                        self.elite_ai_data = None

                # Get recent crypto news analysis
                news_summary = None
                if self.news_aggregator:
                    try:
                        self.logger.info("📰 Fetching recent crypto news...")

                        # Get news from last 1 hour for hourly update (using sync wrapper)
                        recent_news = self.news_aggregator.get_recent_news_sync(hours=1)

                        if recent_news:
                            self.logger.info(f"📰 Found {len(recent_news)} news items in last hour")

                            # Get news summary statistics (using sync wrapper)
                            news_summary = self.news_aggregator.get_news_summary_sync(hours=1)

                            # Add news items list for detailed view
                            news_summary['news_items'] = recent_news[:5]  # Top 5 most recent

                            self.logger.info(
                                f"📊 News summary: {news_summary.get('total_count', 0)} total, "
                                f"Bullish: {news_summary.get('bullish_count', 0)}, "
                                f"Bearish: {news_summary.get('bearish_count', 0)}")
                        else:
                            self.logger.info("📰 No news in the last hour")
                            news_summary = {'total_count': 0, 'news_items': []}
                    except Exception as e:
                        self.logger.error(f"Error fetching news: {e}", exc_info=True)
                        news_summary = None

                # Collect ML model metrics for the notification
                ml_status = self._collect_ml_status()

                # Compute monthly ROI from balance snapshots
                monthly_roi = None
                try:
                    start_balance = self.db.get_start_of_month_balance()
                    raw_stable_balance = balance_data.get('USDT') or balance_data.get('BUSD') or 0
                    current_usdt = float(raw_stable_balance)
                    if start_balance and start_balance > 0 and current_usdt > 0:
                        monthly_roi = (current_usdt - start_balance) / start_balance * 100
                except Exception as e:
                    self.logger.warning(f"Could not compute monthly ROI: {e}")

                # Send notification with AI tactics info, trends, strategy adjustments,
                # Elite AI data, news, and ML model status
                self.notifier.notify_hourly_summary(
                    open_positions_count=open_positions_count,
                    balance_data=balance_data,
                    daily_pnl=daily_pnl,
                    ai_tactics=ai_tactics,
                    trends=trends,
                    strategy_adjustments=strategy_adjustments,
                    elite_ai_data=self.elite_ai_data if hasattr(self, 'elite_ai_data') else None,
                    news_summary=news_summary,
                    daily_trades=daily_trades,
                    ml_status=ml_status,
                    roi=monthly_roi
                )

                # Update last notification time
                self.last_hourly_notification = current_time
                self.logger.info("Hourly status notification sent successfully")

        except Exception as e:
            self.logger.error(f"Error sending hourly notification: {e}", exc_info=True)

    def _collect_ml_status(self) -> dict:
        """Read ML model metrics (accuracy, F1, training date) for all symbols.

        Returns a dict keyed by symbol (e.g. 'BTCUSDT') with their metrics,
        plus optional private keys '_training_active' and '_training_symbol'.
        """
        import json
        import os
        from pathlib import Path

        models_dir = Path(getattr(self.config, 'models_dir', '/var/lib/trading-bot/models'))
        result: dict = {}

        if not models_dir.exists():
            return result

        try:
            for symbol_dir in sorted(models_dir.iterdir()):
                if not symbol_dir.is_dir():
                    continue
                metrics_path = symbol_dir / 'metrics.json'
                if not metrics_path.exists():
                    continue
                try:
                    with open(metrics_path, 'r') as f:
                        metrics = json.load(f)
                    result[symbol_dir.name] = {
                        'accuracy': metrics.get('accuracy', 0),
                        'f1_score': metrics.get('f1_score', 0),
                        'train_samples': metrics.get('train_samples', 0),
                        'training_date': metrics.get('training_date', ''),
                    }
                except Exception as exc:
                    self.logger.debug(f"Could not read ML metrics for {symbol_dir.name}: {exc}")
        except Exception as exc:
            self.logger.warning(f"Could not scan ML models directory: {exc}")

        return result

    def _health_check(self):
        """Perform internal health check"""
        try:
            # Check API connectivity
            self.exchange.ping()

            # Check database
            self.db.health_check()

            # Log status
            open_positions = self.db.get_open_positions()
            self.logger.debug(f"Health check OK - Open positions: {len(open_positions)}")

        except Exception as e:
            self.logger.error(f"Health check failed: {str(e)}")
