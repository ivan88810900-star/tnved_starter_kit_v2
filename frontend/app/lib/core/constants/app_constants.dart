class AppConstants {
  // API Configuration
  static const String devBaseUrl = 'http://127.0.0.1:8000';
  static const String prodBaseUrl = 'https://api.tnved.pro';
  
  // API Endpoints
  static const String healthEndpoint = '/health';
  static const String classifyEndpoint = '/classify';
  static const String codesSearchEndpoint = '/codes/search';
  static const String codesDetailEndpoint = '/codes';
  static const String notesEndpoint = '/notes';
  static const String dataSourcesEndpoint = '/data/sources';
  static const String batchClassifyEndpoint = '/batch/classify_xlsx';
  static const String auditLogsEndpoint = '/audit/logs';
  
  // App Configuration
  static const String appName = 'TN VED Pro';
  static const String appVersion = '1.0.0';
  
  // Animation Durations
  static const Duration shortAnimation = Duration(milliseconds: 200);
  static const Duration mediumAnimation = Duration(milliseconds: 300);
  static const Duration longAnimation = Duration(milliseconds: 500);
  
  // UI Constants
  static const double defaultPadding = 16.0;
  static const double smallPadding = 8.0;
  static const double largePadding = 24.0;
  static const double extraLargePadding = 32.0;
  
  static const double defaultRadius = 8.0;
  static const double smallRadius = 4.0;
  static const double largeRadius = 12.0;
  static const double extraLargeRadius = 16.0;
  
  // File Limits
  static const int maxImageSizeMB = 10;
  static const int maxExcelSizeMB = 50;
  static const List<String> supportedImageFormats = ['jpg', 'jpeg', 'png', 'webp'];
  static const List<String> supportedExcelFormats = ['xlsx', 'xls'];
  
  // Search Configuration
  static const int maxSearchResults = 50;
  static const int maxBatchItems = 1000;
  
  // Hints for Classification
  static const List<String> commonHints = [
    'Материал',
    'Назначение',
    'Комплектность',
    'Размер',
    'Цвет',
    'Происхождение',
    'Способ изготовления',
    'Функциональность',
  ];
}


