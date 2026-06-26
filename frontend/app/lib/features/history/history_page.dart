import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons/lucide_icons.dart';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../../core/services/api_service.dart';
import '../../shared/models/classification.dart';
import '../../shared/widgets/animated_card.dart';

class HistoryPage extends ConsumerStatefulWidget {
  const HistoryPage({super.key});

  @override
  ConsumerState<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends ConsumerState<HistoryPage> {
  List<AuditLog> _logs = [];
  bool _isLoading = false;
  int _currentPage = 0;
  bool _hasMore = true;

  @override
  void initState() {
    super.initState();
    _loadLogs();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('История классификаций'),
        actions: [
          IconButton(
            icon: const Icon(LucideIcons.refreshCw),
            onPressed: _refreshLogs,
          ),
          IconButton(
            icon: const Icon(LucideIcons.filter),
            onPressed: _showFilters,
          ),
        ],
      ),
      body: Column(
        children: [
          // Stats Header
          _buildStatsHeader(),
          
          // Logs List
          Expanded(
            child: _isLoading && _logs.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : _logs.isEmpty
                    ? _buildEmptyState()
                    : _buildLogsList(),
          ),
        ],
      ),
    );
  }

  Widget _buildStatsHeader() {
    return Container(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      decoration: const BoxDecoration(
        border: Border(
          bottom: BorderSide(color: AppTheme.darkBorder, width: 1),
        ),
      ),
      child: Row(
        children: [
          _buildStatItem(
            'Всего',
            _logs.length.toString(),
            LucideIcons.list,
            AppTheme.primaryBlue,
          ),
          const SizedBox(width: 24),
          _buildStatItem(
            'Высокая точность',
            _logs.where((log) => log.confidence >= 0.8).length.toString(),
            LucideIcons.checkCircle,
            AppTheme.success,
          ),
          const SizedBox(width: 24),
          _buildStatItem(
            'Сегодня',
            _logs.where((log) => _isToday(log.createdAt)).length.toString(),
            LucideIcons.calendar,
            AppTheme.gold,
          ),
        ],
      ),
    );
  }

  Widget _buildStatItem(String label, String value, IconData icon, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: color, size: 16),
        const SizedBox(width: 4),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              value,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: AppTheme.darkText,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: AppTheme.darkTextTertiary,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            LucideIcons.history,
            color: AppTheme.darkTextTertiary,
            size: 64,
          ),
          const SizedBox(height: 16),
          Text(
            'История пуста',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
              color: AppTheme.darkTextSecondary,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Здесь будут отображаться результаты классификации',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: AppTheme.darkTextTertiary,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  Widget _buildLogsList() {
    return ListView.builder(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      itemCount: _logs.length + (_hasMore ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == _logs.length) {
          return _buildLoadMoreButton();
        }
        
        final log = _logs[index];
        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: AnimatedCard(
            onTap: () => _showLogDetails(log),
            child: _buildLogCard(log),
          ),
        );
      },
    );
  }

  Widget _buildLogCard(AuditLog log) {
    return Container(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      decoration: BoxDecoration(
        color: AppTheme.darkCard,
        borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
        border: Border.all(color: AppTheme.darkBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: _getConfidenceColor(log.confidence).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: _getConfidenceColor(log.confidence),
                  ),
                ),
                child: Text(
                  log.hsCode,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: _getConfidenceColor(log.confidence),
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: AppTheme.darkCard,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: AppTheme.darkBorder),
                ),
                child: Text(
                  '${(log.confidence * 100).toStringAsFixed(0)}%',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: _getConfidenceColor(log.confidence),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          
          const SizedBox(height: 12),
          
          // Description
          Text(
            log.description,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: AppTheme.darkText,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          
          const SizedBox(height: 12),
          
          // Footer
          Row(
            children: [
              Icon(
                LucideIcons.clock,
                color: AppTheme.darkTextTertiary,
                size: 14,
              ),
              const SizedBox(width: 4),
              Text(
                _formatDateTime(log.createdAt),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppTheme.darkTextTertiary,
                ),
              ),
              const Spacer(),
              Icon(
                LucideIcons.chevronRight,
                color: AppTheme.darkTextTertiary,
                size: 16,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildLoadMoreButton() {
    return Padding(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      child: ElevatedButton.icon(
        onPressed: _hasMore ? _loadMoreLogs : null,
        icon: _isLoading
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(LucideIcons.plus),
        label: Text(_isLoading ? 'Загрузка...' : 'Загрузить еще'),
        style: ElevatedButton.styleFrom(
          backgroundColor: AppTheme.darkCard,
          foregroundColor: AppTheme.darkText,
        ),
      ),
    );
  }

  Future<void> _loadLogs() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final apiService = ref.read(apiServiceProvider);
      final logs = await apiService.getAuditLogs(
        limit: 20,
        offset: _currentPage * 20,
      );

      setState(() {
        _logs = logs.map((json) => AuditLog.fromJson(json)).toList();
        _hasMore = logs.length == 20;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка загрузки истории: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  Future<void> _loadMoreLogs() async {
    if (_isLoading || !_hasMore) return;

    setState(() {
      _isLoading = true;
      _currentPage++;
    });

    try {
      final apiService = ref.read(apiServiceProvider);
      final logs = await apiService.getAuditLogs(
        limit: 20,
        offset: _currentPage * 20,
      );

      setState(() {
        _logs.addAll(logs.map((json) => AuditLog.fromJson(json)));
        _hasMore = logs.length == 20;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
        _currentPage--;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка загрузки: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  Future<void> _refreshLogs() async {
    setState(() {
      _currentPage = 0;
      _logs = [];
      _hasMore = true;
    });
    await _loadLogs();
  }

  void _showFilters() {
    // TODO: Implement filters
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Фильтры будут реализованы'),
        backgroundColor: AppTheme.info,
      ),
    );
  }

  void _showLogDetails(AuditLog log) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Детали классификации'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildDetailRow('Код ТН ВЭД', log.hsCode),
              _buildDetailRow('Описание', log.description),
              _buildDetailRow('Уверенность', '${(log.confidence * 100).toStringAsFixed(1)}%'),
              _buildDetailRow('Дата', _formatDateTime(log.createdAt)),
              const SizedBox(height: 16),
              Text(
                'Обоснование:',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: AppTheme.darkText,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              ...log.rationale.map((item) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 4,
                      height: 4,
                      margin: const EdgeInsets.only(top: 8, right: 8),
                      decoration: const BoxDecoration(
                        color: AppTheme.primaryBlue,
                        shape: BoxShape.circle,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        item,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppTheme.darkTextSecondary,
                        ),
                      ),
                    ),
                  ],
                ),
              )),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Закрыть'),
          ),
        ],
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkText,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _getConfidenceColor(double confidence) {
    if (confidence >= 0.8) return AppTheme.success;
    if (confidence >= 0.6) return AppTheme.warning;
    return AppTheme.error;
  }

  bool _isToday(DateTime date) {
    final now = DateTime.now();
    return date.year == now.year && date.month == now.month && date.day == now.day;
  }

  String _formatDateTime(DateTime date) {
    final now = DateTime.now();
    final difference = now.difference(date);

    if (difference.inDays == 0) {
      return 'Сегодня в ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
    } else if (difference.inDays == 1) {
      return 'Вчера в ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
    } else if (difference.inDays < 7) {
      return '${difference.inDays} дн. назад';
    } else {
      return '${date.day.toString().padLeft(2, '0')}.${date.month.toString().padLeft(2, '0')}.${date.year}';
    }
  }
}


