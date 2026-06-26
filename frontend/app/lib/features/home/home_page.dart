import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons/lucide_icons.dart';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../../shared/widgets/animated_card.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AppTheme.primaryBlue, AppTheme.gold],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(
                LucideIcons.scanLine,
                color: Colors.white,
                size: 20,
              ),
            ),
            const SizedBox(width: 12),
            const Text('TN VED Pro'),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(LucideIcons.settings),
            onPressed: () => context.push('/settings'),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppConstants.defaultPadding),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Welcome Section
              _buildWelcomeSection(context),
              
              const SizedBox(height: AppConstants.largePadding),
              
              // Main Actions Grid
              Expanded(
                child: GridView.count(
                  crossAxisCount: 2,
                  crossAxisSpacing: AppConstants.defaultPadding,
                  mainAxisSpacing: AppConstants.defaultPadding,
                  childAspectRatio: 1.1,
                  children: [
                    _buildActionCard(
                      context,
                      title: 'Классификация',
                      subtitle: 'Определить код ТН ВЭД',
                      icon: LucideIcons.search,
                      color: AppTheme.primaryBlue,
                      onTap: () => context.push('/classify'),
                    ),
                    _buildActionCard(
                      context,
                      title: 'Пакетная обработка',
                      subtitle: 'Массовая классификация',
                      icon: LucideIcons.fileSpreadsheet,
                      color: AppTheme.gold,
                      onTap: () => context.push('/batch'),
                    ),
                    _buildActionCard(
                      context,
                      title: 'Поиск по коду',
                      subtitle: 'Найти товар по коду',
                      icon: LucideIcons.search,
                      color: AppTheme.success,
                      onTap: () => context.push('/explorer'),
                    ),
                    _buildActionCard(
                      context,
                      title: 'История',
                      subtitle: 'Просмотр классификаций',
                      icon: LucideIcons.history,
                      color: AppTheme.warning,
                      onTap: () => context.push('/history'),
                    ),
                  ],
                ),
              ),
              
              const SizedBox(height: AppConstants.defaultPadding),
              
              // Quick Stats
              _buildQuickStats(context),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildWelcomeSection(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Добро пожаловать!',
          style: Theme.of(context).textTheme.displaySmall?.copyWith(
            color: AppTheme.primaryBlue,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          'Выберите действие для работы с классификацией товаров по ТН ВЭД',
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
            color: AppTheme.darkTextSecondary,
          ),
        ),
      ],
    );
  }

  Widget _buildActionCard(
    BuildContext context, {
    required String title,
    required String subtitle,
    required IconData icon,
    required Color color,
    required VoidCallback onTap,
  }) {
    return AnimatedCard(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [
              color.withOpacity(0.1),
              color.withOpacity(0.05),
            ],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(AppConstants.largeRadius),
          border: Border.all(
            color: color.withOpacity(0.2),
            width: 1,
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(AppConstants.defaultPadding),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: color.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  icon,
                  color: color,
                  size: 24,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                title,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: AppTheme.darkText,
                  fontWeight: FontWeight.w600,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppTheme.darkTextSecondary,
                ),
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildQuickStats(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      decoration: BoxDecoration(
        color: AppTheme.darkCard,
        borderRadius: BorderRadius.circular(AppConstants.largeRadius),
        border: Border.all(
          color: AppTheme.darkBorder,
          width: 1,
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _buildStatItem(
            context,
            icon: LucideIcons.database,
            label: 'База данных',
            value: 'Активна',
            color: AppTheme.success,
          ),
          _buildStatItem(
            context,
            icon: LucideIcons.cpu,
            label: 'ИИ модель',
            value: 'Готова',
            color: AppTheme.primaryBlue,
          ),
          _buildStatItem(
            context,
            icon: LucideIcons.clock,
            label: 'Последнее обновление',
            value: 'Сегодня',
            color: AppTheme.gold,
          ),
        ],
      ),
    );
  }

  Widget _buildStatItem(
    BuildContext context, {
    required IconData icon,
    required String label,
    required String value,
    required Color color,
  }) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          icon,
          color: color,
          size: 20,
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
            color: AppTheme.darkText,
            fontWeight: FontWeight.w600,
          ),
        ),
        Text(
          label,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
            color: AppTheme.darkTextTertiary,
          ),
        ),
      ],
    );
  }
}


