import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons/lucide_icons.dart';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../../core/services/api_service.dart';
import '../../shared/models/hs_code.dart';
import '../../shared/widgets/animated_card.dart';
import '../../shared/widgets/hs_code_card.dart';

class ExplorerPage extends ConsumerStatefulWidget {
  const ExplorerPage({super.key});

  @override
  ConsumerState<ExplorerPage> createState() => _ExplorerPageState();
}

class _ExplorerPageState extends ConsumerState<ExplorerPage> {
  final _searchController = TextEditingController();
  List<HSCode> _searchResults = [];
  bool _isSearching = false;
  String? _selectedCode;
  HSCodeDetail? _selectedCodeDetail;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Поиск по коду'),
        actions: [
          IconButton(
            icon: const Icon(LucideIcons.treePine),
            onPressed: _showTreeView,
          ),
        ],
      ),
      body: Row(
        children: [
          // Search Panel
          Expanded(
            flex: 1,
            child: _buildSearchPanel(),
          ),
          
          // Divider
          Container(
            width: 1,
            color: AppTheme.darkBorder,
          ),
          
          // Details Panel
          Expanded(
            flex: 1,
            child: _buildDetailsPanel(),
          ),
        ],
      ),
    );
  }

  Widget _buildSearchPanel() {
    return Column(
      children: [
        // Search Input
        Container(
          padding: const EdgeInsets.all(AppConstants.defaultPadding),
          decoration: const BoxDecoration(
            border: Border(
              bottom: BorderSide(color: AppTheme.darkBorder, width: 1),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Поиск по коду ТН ВЭД',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: AppTheme.darkText,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: 'Введите код или описание товара...',
                  prefixIcon: const Icon(LucideIcons.search),
                  suffixIcon: _searchController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(LucideIcons.x),
                          onPressed: _clearSearch,
                        )
                      : null,
                ),
                onChanged: _onSearchChanged,
                onSubmitted: _performSearch,
              ),
              const SizedBox(height: 8),
              Text(
                'Например: 1234.56.78.90 или "пластиковые изделия"',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppTheme.darkTextTertiary,
                ),
              ),
            ],
          ),
        ),
        
        // Search Results
        Expanded(
          child: _buildSearchResults(),
        ),
      ],
    );
  }

  Widget _buildSearchResults() {
    if (_isSearching) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 16),
            Text('Поиск...'),
          ],
        ),
      );
    }

    if (_searchResults.isEmpty && _searchController.text.isNotEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              LucideIcons.searchX,
              color: AppTheme.darkTextTertiary,
              size: 48,
            ),
            const SizedBox(height: 16),
            Text(
              'Ничего не найдено',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
            Text(
              'Попробуйте изменить поисковый запрос',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextTertiary,
              ),
            ),
          ],
        ),
      );
    }

    if (_searchResults.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              LucideIcons.search,
              color: AppTheme.darkTextTertiary,
              size: 48,
            ),
            const SizedBox(height: 16),
            Text(
              'Начните поиск',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
            Text(
              'Введите код или описание товара',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextTertiary,
              ),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      itemCount: _searchResults.length,
      itemBuilder: (context, index) {
        final code = _searchResults[index];
        final isSelected = _selectedCode == code.code;
        
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: AnimatedCard(
            onTap: () => _selectCode(code.code),
            child: Container(
              decoration: BoxDecoration(
                color: isSelected ? AppTheme.primaryBlue.withOpacity(0.1) : AppTheme.darkCard,
                borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
                border: Border.all(
                  color: isSelected ? AppTheme.primaryBlue : AppTheme.darkBorder,
                  width: isSelected ? 2 : 1,
                ),
              ),
              child: HSCodeCard(
                code: code,
                isSelected: isSelected,
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildDetailsPanel() {
    return Column(
      children: [
        // Header
        Container(
          padding: const EdgeInsets.all(AppConstants.defaultPadding),
          decoration: const BoxDecoration(
            border: Border(
              bottom: BorderSide(color: AppTheme.darkBorder, width: 1),
            ),
          ),
          child: Row(
            children: [
              const Icon(
                LucideIcons.info,
                color: AppTheme.primaryBlue,
                size: 24,
              ),
              const SizedBox(width: 12),
              Text(
                'Детали кода',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: AppTheme.darkText,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        
        // Content
        Expanded(
          child: _selectedCodeDetail != null
              ? _buildCodeDetails()
              : _buildEmptyState(),
        ),
      ],
    );
  }

  Widget _buildCodeDetails() {
    final detail = _selectedCodeDetail!;
    
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Basic Info
          _buildBasicInfo(detail.hsCode),
          
          const SizedBox(height: AppConstants.largePadding),
          
          // Tariff Rates
          if (detail.tariffRates.isNotEmpty) _buildTariffRates(detail.tariffRates),
          
          const SizedBox(height: AppConstants.largePadding),
          
          // NTM Measures
          if (detail.ntmMeasures.isNotEmpty) _buildNTMMeasures(detail.ntmMeasures),
          
          const SizedBox(height: AppConstants.largePadding),
          
          // Notes
          if (detail.notes.isNotEmpty) _buildNotes(detail.notes),
        ],
      ),
    );
  }

  Widget _buildBasicInfo(HSCode code) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.hash,
                  color: AppTheme.primaryBlue,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Text(
                  'Основная информация',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: AppTheme.primaryBlue,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            _buildInfoRow('Код ТН ВЭД', code.code),
            _buildInfoRow('Название (RU)', code.titleRu),
            if (code.titleEn != null) _buildInfoRow('Название (EN)', code.titleEn!),
            if (code.chapter != null) _buildInfoRow('Глава', code.chapter!),
            if (code.heading != null) _buildInfoRow('Позиция', code.heading!),
            if (code.subheading != null) _buildInfoRow('Подпозиция', code.subheading!),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
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

  Widget _buildTariffRates(List<TariffRate> rates) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.percent,
                  color: AppTheme.gold,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Text(
                  'Тарифные ставки',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: AppTheme.gold,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ...rates.map((rate) => Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.darkCard,
                borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
                border: Border.all(color: AppTheme.darkBorder),
              ),
              child: Column(
                children: [
                  _buildInfoRow('Таможенная пошлина', rate.duty),
                  _buildInfoRow('НДС', rate.vat),
                  if (rate.add != null) _buildInfoRow('Дополнительные сборы', rate.add!),
                  _buildInfoRow('Версия источника', rate.sourceVersion),
                ],
              ),
            )),
          ],
        ),
      ),
    );
  }

  Widget _buildNTMMeasures(List<NTMMeasure> measures) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.shield,
                  color: AppTheme.warning,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Text(
                  'Нетарифные меры',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: AppTheme.warning,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ...measures.map((measure) => Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.darkCard,
                borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
                border: Border.all(color: AppTheme.darkBorder),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    measure.title,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      color: AppTheme.darkText,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 4),
                  _buildInfoRow('Основание', measure.basis),
                  if (measure.country != null) _buildInfoRow('Страна', measure.country!),
                  if (measure.notes != null) _buildInfoRow('Примечания', measure.notes!),
                ],
              ),
            )),
          ],
        ),
      ),
    );
  }

  Widget _buildNotes(List<Note> notes) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.fileText,
                  color: AppTheme.info,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Text(
                  'Примечания',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: AppTheme.info,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ...notes.map((note) => Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.darkCard,
                borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
                border: Border.all(color: AppTheme.darkBorder),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        '${note.level.toUpperCase()} ${note.refId}',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          color: AppTheme.info,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    note.text,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppTheme.darkTextSecondary,
                    ),
                  ),
                ],
              ),
            )),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            LucideIcons.search,
            color: AppTheme.darkTextTertiary,
            size: 48,
          ),
          const SizedBox(height: 16),
          Text(
            'Выберите код для просмотра деталей',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: AppTheme.darkTextSecondary,
            ),
          ),
        ],
      ),
    );
  }

  void _onSearchChanged(String value) {
    setState(() {});
  }

  void _clearSearch() {
    _searchController.clear();
    setState(() {
      _searchResults = [];
      _selectedCode = null;
      _selectedCodeDetail = null;
    });
  }

  Future<void> _performSearch(String query) async {
    if (query.trim().isEmpty) return;

    setState(() {
      _isSearching = true;
    });

    try {
      final apiService = ref.read(apiServiceProvider);
      final results = await apiService.searchCodes(query);
      
      setState(() {
        _searchResults = results.map((json) => HSCode.fromJson(json)).toList();
        _isSearching = false;
      });
    } catch (e) {
      setState(() {
        _isSearching = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка поиска: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  Future<void> _selectCode(String code) async {
    setState(() {
      _selectedCode = code;
    });

    try {
      final apiService = ref.read(apiServiceProvider);
      final detail = await apiService.getCodeDetails(code);
      
      setState(() {
        _selectedCodeDetail = HSCodeDetail.fromJson(detail);
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка загрузки деталей: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  void _showTreeView() {
    // TODO: Implement tree view
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Древовидный просмотр будет реализован'),
        backgroundColor: AppTheme.info,
      ),
    );
  }
}


